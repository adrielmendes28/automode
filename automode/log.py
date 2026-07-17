"""Logging and desktop notifications.

automode never writes to the terminal while an agent owns it — a stray line
would corrupt the TUI — so everything it has to say goes to a log file, plus
an optional system notification.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import log_path

MAX_LOG_BYTES = 1_000_000


class Logger:
    def __init__(self, enabled: bool = True, path: Path | None = None):
        self.enabled = enabled
        self.path = path or log_path()

    def __call__(self, message: str) -> None:
        if not self.enabled:
            return
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate()
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{stamp}] {message}\n")
        except OSError:
            pass  # logging must never take a session down

    def _rotate(self) -> None:
        try:
            if self.path.stat().st_size > MAX_LOG_BYTES:
                self.path.replace(self.path.with_suffix(".log.1"))
        except OSError:
            pass


def notify(title: str, message: str) -> None:
    """Fire-and-forget desktop notification (macOS only, best effort)."""
    if sys.platform != "darwin":
        return
    safe_title = title.replace('"', "'")
    safe_message = message.replace('"', "'")
    script = f'display notification "{safe_message}" with title "{safe_title}"'
    try:
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
