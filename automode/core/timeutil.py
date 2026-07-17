"""Timezone discovery and wall-clock arithmetic."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_ZONEINFO_MARKER = "/zoneinfo/"

WEEKDAYS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def local_tz_name() -> str:
    """Best-effort IANA name for the system timezone."""
    env = os.environ.get("TZ")
    if env:
        try:
            ZoneInfo(env)
            return env
        except Exception:
            pass
    try:
        path = os.path.realpath("/etc/localtime")
        marker = path.find(_ZONEINFO_MARKER)
        if marker != -1:
            name = path[marker + len(_ZONEINFO_MARKER) :]
            ZoneInfo(name)
            return name
    except Exception:
        pass
    return "UTC"


def get_tz(name: str | None) -> ZoneInfo:
    """Resolve a timezone name, falling back to the system zone."""
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    try:
        return ZoneInfo(local_tz_name())
    except Exception:
        return ZoneInfo("UTC")


def to_24h(hour: int, ampm: str | None) -> int:
    """Convert a 12-hour clock reading to 24-hour."""
    if not ampm:
        return hour % 24
    if ampm.lower().startswith("p"):
        return hour % 12 + 12
    return hour % 12


def next_occurrence(
    now: datetime,
    hour: int,
    minute: int,
    tz: ZoneInfo,
    weekday: int | None = None,
    slack: timedelta = timedelta(minutes=2),
) -> datetime:
    """The next time the wall clock in `tz` reads hour:minute.

    A reading that just passed (within `slack`) counts as now rather than
    a whole day away: the agent prints the message a beat before the reset.
    Arithmetic runs on naive local time so a DST shift moves the wall clock,
    not the appointment.
    """
    local_now = now.astimezone(tz).replace(tzinfo=None)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if weekday is None:
        if candidate < local_now - slack:
            candidate += timedelta(days=1)
    else:
        for days in range(8):
            shifted = candidate + timedelta(days=days)
            if shifted.weekday() == weekday and shifted >= local_now - slack:
                candidate = shifted
                break
    return candidate.replace(tzinfo=tz)


def parse_hhmm(text: str) -> tuple[int, int] | None:
    """Parse a "HH:MM" config entry."""
    parts = text.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None
