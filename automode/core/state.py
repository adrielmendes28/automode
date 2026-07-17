"""Remember which scheduled pings already fired, across restarts."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .config import state_dir

# A ping record older than this cannot suppress anything; drop it.
RECORD_TTL = 3 * 24 * 3600


def state_path() -> Path:
    return state_dir() / "state.json"


class State:
    def __init__(self, path: Path | None = None):
        self.path = path or state_path()
        self.data = self._read()

    def _read(self) -> dict:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                data.setdefault("pings", {})
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        return {"pings": {}}

    def save(self) -> None:
        self._prune()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass  # state is a convenience, never worth crashing a session over

    def _prune(self) -> None:
        cutoff = time.time() - RECORD_TTL
        self.data["pings"] = {
            key: at for key, at in self.data["pings"].items() if at >= cutoff
        }

    def ping_fired(self, key: str) -> bool:
        return key in self.data.get("pings", {})

    def mark_ping(self, key: str) -> None:
        self.data.setdefault("pings", {})[key] = time.time()
        self.save()
