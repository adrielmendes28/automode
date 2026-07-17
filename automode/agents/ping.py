"""Headless pings and the launchd agent that fires them.

The in-session ping needs a session. This is the version that works while you
are asleep and the terminal is closed: a one-shot prompt that opens the usage
window and exits.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from .. import REPO_ROOT
from ..core.config import log_path, state_dir
from ..core.timeutil import parse_hhmm

LABEL = "com.automode.ping"
AGENTS = ("claude", "codex")
PING_TIMEOUT = 300


def headless_argv(agent: str, message: str) -> list[str]:
    if agent == "claude":
        return ["claude", "-p", message]
    if agent == "codex":
        return ["codex", "exec", message]
    raise ValueError(f"unknown agent: {agent}")


def ping_once(agent: str, message: str, log=None) -> int:
    """Send one message to the agent, non-interactively."""
    argv = headless_argv(agent, message)
    if shutil.which(argv[0]) is None:
        if log:
            log(f"ping: {argv[0]} not found on PATH")
        return 127
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=PING_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        if log:
            log(f"ping {agent}: timed out after {PING_TIMEOUT}s")
        return 124
    except OSError as exc:
        if log:
            log(f"ping {agent}: {exc}")
        return 1

    reply = (result.stdout or result.stderr or "").strip().replace("\n", " ")
    if log:
        log(f"ping {agent} {message!r} -> rc={result.returncode} {reply[:200]!r}")
    return result.returncode


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _launchd_path() -> str:
    """A PATH that finds the agents. launchd starts with almost nothing."""
    parts: list[str] = []
    for name in AGENTS:
        found = shutil.which(name)
        if found:
            parent = str(Path(found).parent)
            if parent not in parts:
                parts.append(parent)
    for default in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"):
        if default not in parts:
            parts.append(default)
    return ":".join(parts)


def _program_arguments(agent: str, message: str) -> list[str]:
    """How launchd should invoke us.

    Prefer the installed `automode` script. Falling back to `python -m automode`
    only works if the package is importable, which is why install() also pins a
    working directory. Otherwise the 5am ping would fail silently, months from
    now, with nobody awake to see it.
    """
    args = ["ping", "--agent", agent, "--message", message]
    script = shutil.which("automode")
    if script:
        return [script, *args]
    return [sys.executable, "-m", "automode", *args]


def build_plist(times: list[str], agent: str, message: str) -> dict:
    intervals = []
    for entry in times:
        parsed = parse_hhmm(str(entry))
        if parsed is None:
            continue
        hour, minute = parsed
        intervals.append({"Hour": hour, "Minute": minute})
    if not intervals:
        raise ValueError("no valid times configured")

    out = state_dir() / "launchd.log"
    return {
        "Label": LABEL,
        "ProgramArguments": _program_arguments(agent, message),
        "StartCalendarInterval": intervals,
        "RunAtLoad": False,
        # launchd starts with almost no environment; without this it would not
        # even find `claude` on PATH.
        "EnvironmentVariables": {"PATH": _launchd_path(), "HOME": str(Path.home())},
        "WorkingDirectory": str(REPO_ROOT),
        "StandardOutPath": str(out),
        "StandardErrorPath": str(out),
        "ProcessType": "Background",
    }


def _launchctl(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["launchctl", *args], capture_output=True, text=True, check=False
    )


def install(config: dict) -> int:
    ping = config.get("ping", {})
    times = list(ping.get("times", []))
    agent = ping.get("agent", "claude")
    message = ping.get("message", "oi")

    if sys.platform != "darwin":
        print("automode: launchd scheduling is macOS only.")
        return 1
    try:
        plist = build_plist(times, agent, message)
    except ValueError as exc:
        print(f"automode: {exc}")
        return 1

    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state_dir().mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(plist, handle)

    target = f"gui/{os.getuid()}"
    _launchctl(["bootout", f"{target}/{LABEL}"])  # ignore if it was not loaded
    result = _launchctl(["bootstrap", target, str(path)])
    if result.returncode != 0:
        legacy = _launchctl(["load", "-w", str(path)])
        if legacy.returncode != 0:
            print(f"automode: launchctl failed: {result.stderr.strip()}")
            return 1

    print(f"automode: scheduled. plist at {path}")
    print(f"  agent:    {agent}")
    print(f"  message:  {message!r}")
    print(f"  times:    {', '.join(times)}")
    print(f"  log:      {state_dir() / 'launchd.log'}")
    print()
    print("IMPORTANT: launchd does not wake the Mac. If it is asleep at the")
    print("scheduled time the ping only fires once it wakes, which defeats the")
    print("point. Schedule the wake too (needs sudo, run it yourself):")
    print()
    earliest = _earliest(times)
    if earliest:
        print(f"  sudo pmset repeat wakeorpoweron MTWRFSU {earliest}")
    print()
    return 0


def _earliest(times: list[str]) -> str | None:
    """Wake a couple of minutes before the first ping of the day."""
    parsed = [parse_hhmm(str(entry)) for entry in times]
    valid = [item for item in parsed if item]
    if not valid:
        return None
    hour, minute = min(valid)
    total = max(hour * 60 + minute - 2, 0)
    return f"{total // 60:02d}:{total % 60:02d}:00"


def uninstall() -> int:
    path = plist_path()
    _launchctl(["bootout", f"gui/{os.getuid()}/{LABEL}"])
    _launchctl(["unload", str(path)])
    if path.exists():
        path.unlink()
        print(f"automode: removed {path}")
    else:
        print("automode: nothing was scheduled")
    print("If you scheduled a wake, undo it with: sudo pmset repeat cancel")
    return 0


def status() -> int:
    path = plist_path()
    if not path.exists():
        print("launchd:  not installed (use `automode schedule install`)")
        return 0
    result = _launchctl(["list", LABEL])
    loaded = "loaded" if result.returncode == 0 else "NOT loaded"
    print(f"launchd:  {loaded} ({path})")
    try:
        with path.open("rb") as handle:
            plist = plistlib.load(handle)
        intervals = plist.get("StartCalendarInterval", [])
        times = ", ".join(
            f"{item.get('Hour', 0):02d}:{item.get('Minute', 0):02d}"
            for item in intervals
        )
        argv = plist.get("ProgramArguments", [])
        agent = argv[argv.index("--agent") + 1] if "--agent" in argv else "?"
        print(f"          times:  {times}")
        print(f"          agent:  {agent}")
    except (OSError, ValueError, IndexError):
        pass
    print(f"          log: {state_dir() / 'launchd.log'}")
    print("          system wake: pmset repeat (see `pmset -g sched`)")
    print(f"          automode log: {log_path()}")
    return 0
