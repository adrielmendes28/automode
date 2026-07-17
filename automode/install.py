"""`automode install` — one command to make `claude` and `codex` wear the mods.

Two pieces have to line up:

  1. an `automode` executable on your PATH, and
  2. shell aliases pointing `claude`/`codex` at it.

Piece 1 is usually pip's job, but this has to work for someone who cloned the
repo and has neither pipx nor uv. So if `automode` is not already on the PATH,
we drop a three-line launcher that runs the package straight from the clone.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path

from . import REPO_ROOT

MARKER = "# automode"
BLOCK = """
{marker} — auto continue + auto ping for claude code / codex
alias claude='automode claude'
alias codex='automode codex'
"""

LAUNCHER = """#!/bin/sh
{marker} launcher — runs the package straight from the clone.
# Delete this file if you later install automode with pipx or uv.
AUTOMODE_HOME="{home}"
export PYTHONPATH="$AUTOMODE_HOME${{PYTHONPATH:+:$PYTHONPATH}}"
exec "{python}" -m automode "$@"
"""


def bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def launcher_path() -> Path:
    return bin_dir() / "automode"


def shell_rc(shell: str | None = None) -> Path | None:
    """The rc file for the user's shell, or None if we do not know it."""
    name = shell if shell is not None else os.environ.get("SHELL", "")
    home = Path.home()
    if "zsh" in name:
        return home / ".zshrc"
    if "bash" in name:
        return home / ".bashrc"
    if "fish" in name:
        return home / ".config" / "fish" / "config.fish"
    return None


def on_path(directory: Path) -> bool:
    entries = os.environ.get("PATH", "").split(os.pathsep)
    return str(directory) in entries


def write_launcher() -> Path:
    path = launcher_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        LAUNCHER.format(marker=MARKER, home=REPO_ROOT, python=sys.executable)
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def install_aliases() -> int:
    print("automode install\n")

    installed = shutil.which("automode")
    if installed and Path(installed) != launcher_path():
        print(f"  automode found at {installed}")
    else:
        path = write_launcher()
        print(f"  launcher written to {path}")
        if not on_path(bin_dir()):
            print(f"  WARNING: {bin_dir()} is not on your PATH. Add this first:")
            print(f'    export PATH="{bin_dir()}:$PATH"')

    rc = shell_rc()
    if rc is None:
        print("\n  Unknown shell — add these lines yourself:")
        print(BLOCK.format(marker=MARKER))
        return 1

    try:
        existing = rc.read_text(encoding="utf-8")
    except OSError:
        existing = ""

    if "alias claude='automode claude'" in existing:
        print(f"  aliases already in {rc}")
    else:
        try:
            with rc.open("a", encoding="utf-8") as handle:
                handle.write(BLOCK.format(marker=MARKER))
        except OSError as exc:
            print(f"  could not write {rc}: {exc}")
            return 1
        print(f"  aliases added to {rc}")

    # Aliases live in the shell, not in the file: a terminal that is already
    # open kept whatever it read at startup and will not pick these up.
    print(f"\n  NOTE: your open terminals do not have these yet.")
    print(f"  Run `source {rc}` in each, or just open a new one.\n")
    print("Then:")
    for key, what in (
        ("claude", "the agent, with the mods"),
        ("\\claude", "the agent, bare (the backslash skips the alias)"),
        (hotkey(), "the menu, from inside a session"),
    ):
        print(f"  {key:<16} {what}")
    return 0


def hotkey() -> str:
    """Whatever hotkey is actually configured — never assume the default."""
    from .core import config as configmod
    from .terminal.overlay import describe_hotkey

    return describe_hotkey(str(configmod.load().get("hotkey", "ctrl+g")))


def uninstall_aliases() -> int:
    print("automode uninstall\n")

    rc = shell_rc()
    if rc is not None and rc.exists():
        try:
            lines = rc.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            lines = []
        kept = [
            line
            for line in lines
            if MARKER not in line
            and "alias claude='automode claude'" not in line
            and "alias codex='automode codex'" not in line
        ]
        if len(kept) != len(lines):
            rc.write_text("".join(kept), encoding="utf-8")
            print(f"  aliases removed from {rc}")
        else:
            print(f"  no aliases found in {rc}")

    path = launcher_path()
    if path.exists() and MARKER in path.read_text(encoding="utf-8", errors="ignore"):
        path.unlink()
        print(f"  launcher removed from {path}")

    print("\nThe config stays put. Delete it with:")
    print("  rm -rf ~/.config/automode ~/.local/state/automode")
    print("Scheduled pings are separate: automode schedule uninstall")
    return 0
