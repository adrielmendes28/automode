"""Command line entry point.

Dispatch is by hand rather than argparse: `automode claude -p "hi" --model x`
has to hand every flag to claude untouched, and argparse would claim them.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__, install
from .agents import detect, dialogs
from .agents import ping as pingmod
from .controller import Controller
from .core import config as configmod
from .core.i18n import set_language, t
from .core.log import Logger
from .core.state import State
from .core.timeutil import get_tz, local_tz_name, parse_hhmm
from .terminal import menu
from .terminal import overlay as overlaymod
from .terminal import runner as pty_runner
from .terminal.runner import run as pty_run

WRAPPABLE = ("claude", "codex")

USAGE = """automode {version} — {tagline}

  automode claude [args...]     run claude with the mods (args pass through)
  automode codex  [args...]     same for codex
  automode -- <cmd> [args...]   wrap any other command

  automode install              install the `claude` and `codex` aliases
  automode menu                 open the settings menu
  automode status               show settings and what is scheduled
  automode doctor               check the detector against known limit messages
  automode ping                 send the ping now, with no session open
  automode schedule install     schedule the ping with launchd (macOS)
  automode schedule uninstall   remove the schedule
  automode uninstall            remove the aliases and the launcher

{hotkey_line}
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    set_language(str(configmod.load().get("language", "en")))

    if not args or args[0] in ("-h", "--help", "help"):
        return cmd_usage()
    if args[0] in ("-V", "--version", "version"):
        print(f"automode {__version__}")
        return 0

    command, rest = args[0], args[1:]
    handlers = {
        "install": lambda: install.install_aliases(),
        "uninstall": lambda: install.uninstall_aliases(),
        "menu": menu.run_standalone,
        "config": menu.run_standalone,
        "status": cmd_status,
        "doctor": cmd_doctor,
    }

    if command in WRAPPABLE:
        return cmd_wrap([command, *rest])
    if command == "--":
        return cmd_wrap(rest) if rest else cmd_usage(1)
    if command in handlers:
        return handlers[command]()
    if command == "ping":
        return cmd_ping(rest)
    if command == "schedule":
        return cmd_schedule(rest)

    sys.stderr.write(t("cli.unknown_command", command=command) + "\n\n")
    return cmd_usage(1)


def cmd_usage(code: int = 0) -> int:
    config = configmod.load()
    hotkey = overlaymod.describe_hotkey(str(config.get("hotkey", "ctrl+g")))
    stream = sys.stderr if code else sys.stdout
    stream.write(
        USAGE.format(
            version=__version__,
            tagline=t("cli.tagline"),
            hotkey_line=t("cli.hotkey_line", hotkey=hotkey),
        )
    )
    return code


def cmd_wrap(argv: list[str]) -> int:
    if pty_runner.session_depth() >= pty_runner.MAX_DEPTH:
        # Something is calling us in a loop — a shell function or a script named
        # `claude` that invokes automode again. Run the agent bare and stop.
        os.execvp(argv[0], argv)

    if shutil.which(argv[0]) is None:
        sys.stderr.write(f"automode: {argv[0]!r} is not on your PATH\n")
        return 127

    config = configmod.load()
    log = Logger(enabled=True)
    log(f"session: {' '.join(argv)}")
    controller = Controller(config, log=log, state=State())
    overlay = overlaymod.build(config, agent=argv[0], size=menu.terminal_size())
    if overlay is None:
        log(f"hotkey {config.get('hotkey')!r} is unusable — menu off this session")
    return pty_run(argv, controller, overlay=overlay)


def cmd_status() -> int:
    config = configmod.load()
    tz_name = config.get("timezone") or local_tz_name()
    tz = get_tz(config.get("timezone") or None)
    now = datetime.now(tz)
    hotkey = overlaymod.describe_hotkey(str(config.get("hotkey", "ctrl+g")))

    print(f"automode {__version__}")
    print(f"config:   {configmod.config_path()}")
    print(f"log:      {configmod.log_path()}")
    print(f"timezone: {tz_name}  (now {now:%H:%M})")
    print()
    print(f"auto continue: {_on_off(config.get('auto_continue'))}")
    print(f"  message:     {config.get('continue_message')!r}")
    print(f"  wait:        {config.get('grace_seconds')}s past the reset")
    print(f"  limit menu:  {_on_off(config.get('answer_limit_prompt'))}")
    print(f"  menu hotkey: {hotkey}")
    print()

    ping = config.get("ping", {})
    print(f"auto ping {ping.get('message', 'hi')!r}: {_on_off(ping.get('enabled'))}")
    state = State()
    for entry in ping.get("times", []):
        print(f"  {_ping_line(entry, now, state)}")
    print()
    return pingmod.status()


def _on_off(value: object) -> str:
    return "on" if value else "off"


def _ping_line(entry: str, now: datetime, state: State) -> str:
    parsed = parse_hhmm(str(entry))
    if parsed is None:
        return f"{entry}  (invalid)"
    hour, minute = parsed
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target < now:
        target += timedelta(days=1)
    delta = target - now
    hours, rest = divmod(int(delta.total_seconds()), 3600)
    done = " (already sent today)" if state.ping_fired(f"{now:%Y-%m-%d} {entry}") else ""
    return f"{entry}  next in {hours}h{rest // 60:02d}min{done}"


def cmd_doctor() -> int:
    config = configmod.load()
    tz = get_tz(config.get("timezone") or None)
    now = datetime.now(tz)
    failures = 0

    print(f"now: {now:%Y-%m-%d %H:%M:%S %Z}\n")
    print("limit messages:")
    for sample in detect.SAMPLES:
        hit = detect.scan(detect.normalize(sample), now, tz)
        short = sample if len(sample) <= 66 else sample[:63] + "..."
        if hit is None:
            failures += 1
            print(f"  NOT RECOGNISED  {short}")
            continue
        local = hit.reset_at.astimezone(tz)
        mark = "ok " if detect.plausible(hit.reset_at, now) else "??? "
        print(f"  {mark} {local:%d/%m %H:%M}  [{hit.kind}]  {short}")

    print("\nblocking menus:")
    for name, expected, sample in dialogs.SAMPLES:
        answer = dialogs.find(detect.normalize(sample))
        if answer is None or answer.key != expected:
            failures += 1
            print(f"  NOT RECOGNISED  {name}")
        else:
            print(f"  ok  {name} -> picks option {answer.key}")

    print("\nagents:")
    for name in WRAPPABLE:
        print(f"  {name}: {shutil.which(name) or 'not on PATH'}")

    hotkey = overlaymod.parse_hotkeys(str(config.get("hotkey", "ctrl+g")))
    print(f"\nhotkey: {config.get('hotkey')!r} -> {hotkey}")
    if not hotkey:
        failures += 1
        print("  unusable — the menu will not open")

    depth = pty_runner.session_depth()
    if depth:
        print(f"\nnote: already inside {depth} automode session(s)")
    return 1 if failures else 0


def cmd_ping(args: list[str]) -> int:
    config = configmod.load()
    ping = config.get("ping", {})
    agent = ping.get("agent", "claude")
    message = ping.get("message", "hi")

    index = 0
    while index < len(args):
        flag = args[index]
        if flag in ("--agent", "--message") and index + 1 < len(args):
            if flag == "--agent":
                agent = args[index + 1]
            else:
                message = args[index + 1]
            index += 2
        else:
            sys.stderr.write(f"automode ping: bad argument: {flag}\n")
            return 2

    if agent not in pingmod.AGENTS:
        sys.stderr.write(f"automode ping: unknown agent: {agent}\n")
        return 2

    code = pingmod.ping_once(agent, message, log=Logger(enabled=True))
    if code == 0:
        print(f"automode: sent {message!r} to {agent} — window is open.")
    else:
        print(f"automode: ping failed (rc={code}); see {configmod.log_path()}")
    return code


def cmd_schedule(args: list[str]) -> int:
    action = args[0] if args else "status"
    if action == "install":
        return pingmod.install(configmod.load())
    if action in ("uninstall", "remove"):
        return pingmod.uninstall()
    if action == "status":
        return pingmod.status()
    sys.stderr.write("automode schedule: use install | uninstall | status\n")
    return 2
