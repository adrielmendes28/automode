"""Load and save ~/.config/automode/config.toml."""

from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    # Auto continue
    "auto_continue": True,
    "continue_message": "continue",
    "answer_limit_prompt": True,
    "grace_seconds": 60,
    "idle_guard_seconds": 5,
    # General
    "language": "en",
    "timezone": "",  # empty = system timezone
    "notify": True,
    # ctrl+g reaches us from any terminal. alt+g only arrives if the terminal
    # is set to send Option as Meta, which macOS does not do by default.
    "hotkey": "ctrl+g, alt+g",
    # Auto ping
    "ping": {
        "enabled": False,
        "message": "hi",
        "times": ["05:00", "17:00"],
        "agent": "claude",
        "catchup_minutes": 30,
        "idle_seconds": 20,
    },
}

HEADER = """\
# automode: https://github.com/adrielmendes28/automode
# Written by `automode menu`. Hand-edit freely, but saving from the menu
# rewrites this file and drops comments.

"""


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "automode"


def config_path() -> Path:
    return config_dir() / "config.toml"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "automode"


def log_path() -> Path:
    return state_dir() / "automode.log"


def default_for(path: tuple[str, ...]):
    """The shipped default at a config path, for repairing bad values."""
    node = DEFAULTS
    for key in path:
        node = node[key]
    return copy.deepcopy(node)


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load() -> dict[str, Any]:
    """Config from disk merged over the defaults; defaults alone if unreadable."""
    path = config_path()
    try:
        with path.open("rb") as handle:
            return _merge(DEFAULTS, tomllib.load(handle))
    except FileNotFoundError:
        return copy.deepcopy(DEFAULTS)
    except (tomllib.TOMLDecodeError, OSError):
        return copy.deepcopy(DEFAULTS)


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_fmt(item) for item in value) + "]"
    raise TypeError(f"cannot serialize {type(value).__name__} to TOML")


def dumps(config: dict[str, Any]) -> str:
    """Minimal TOML writer. The stdlib reads TOML but cannot write it."""
    scalars: list[str] = []
    tables: list[tuple[str, dict]] = []
    for key, value in config.items():
        if isinstance(value, dict):
            tables.append((key, value))
        else:
            scalars.append(f"{key} = {_fmt(value)}")
    lines = list(scalars)
    for name, table in tables:
        lines.append("")
        lines.append(f"[{name}]")
        for key, value in table.items():
            lines.append(f"{key} = {_fmt(value)}")
    return HEADER + "\n".join(lines) + "\n"


def save(config: dict[str, Any]) -> Path:
    """Write the config atomically so a crash cannot truncate it."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(dumps(config), encoding="utf-8")
    os.replace(tmp, path)
    return path
