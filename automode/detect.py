"""Find usage-limit messages in a live TUI byte stream.

The agents redraw their whole screen constantly and wrap the message inside
box borders, so the text never arrives as one clean line. Everything here
exists to turn that mess back into a flat string a regex can read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .timeutil import WEEKDAYS, get_tz, next_occurrence, to_24h

ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"  # CSI: colors, cursor moves
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC: window title
    r"|\x1b[PX^_][^\x1b]*\x1b\\"  # DCS/SOS/PM/APC
    r"|\x1b[@-Z\\-_]"  # two-byte escapes
)

# An escape sequence split across two reads is held back for the next chunk.
# Past this length it is not a real sequence, just a stray ESC byte.
MAX_ESC_HOLD = 32

BOX_RE = re.compile("[─-╿]")  # box drawing: the TUI frame
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WS_RE = re.compile(r"\s+")

# Match in two steps: a trigger phrase first, then a time reading close to it.
# One big regex would happily fire on any "resets 6pm" elsewhere on screen.
TRIGGER_RE = re.compile(
    r"(?:hit|reached)\s+(?:your\s+)?(?:[\w-]+\s+){0,3}limit"
    r"|limit\s+(?:has\s+been\s+)?reached"
    r"|usage\s+limit"
    r"|out\s+of\s+(?:usage|credits)",
    re.I,
)
WINDOW_CHARS = 400

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# codex: "... or try again at Jul 23rd, 2026 1:16 AM."
ABSOLUTE_RE = re.compile(
    r"try\s+again\s+at\s+"
    r"(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+"
    r"(?P<year>\d{4})\s+"
    r"(?P<hour>\d{1,2}):(?P<min>\d{2})\s*(?P<ampm>[ap])\.?m\.?",
    re.I,
)

# claude: "resets 6:20pm (America/Sao_Paulo)", "will reset at 4pm", "resets Tue 9am"
CLOCK_RE = re.compile(
    r"resets?\s*(?:at|on)?\s+"
    r"(?:(?P<dow>mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+)?"
    r"(?P<hour>\d{1,2})(?::(?P<min>\d{2}))?\s*(?P<ampm>am|pm)"
    r"(?:\s*\((?P<tz>[A-Za-z][A-Za-z0-9_+\-]*(?:/[A-Za-z0-9_+\-]+)*)\))?",
    re.I,
)

RELATIVE_RE = re.compile(
    r"(?:try\s+again|resets?)\s+in\s+"
    r"(?:(?P<hours>\d+)\s*(?:hours?|hrs?|h)\b)?\s*"
    r"(?:(?:and\s+)?(?P<mins>\d+)\s*(?:minutes?|mins?|m)\b)?",
    re.I,
)

# A reset further out than this is a misread, not a rate limit.
MAX_HORIZON = timedelta(days=8)
MAX_PAST = timedelta(hours=1)


@dataclass(frozen=True)
class LimitHit:
    """A parsed usage-limit message."""

    reset_at: datetime
    kind: str
    raw: str


def strip_ansi_stream(text: str) -> tuple[str, str]:
    """Remove escape sequences, returning (clean, leftover).

    `leftover` is a sequence that looks cut off at the end of the chunk; feed
    it back in front of the next read.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char != "\x1b":
            out.append(char)
            index += 1
            continue
        match = ANSI_RE.match(text, index)
        if match:
            index = match.end()
            continue
        if length - index < MAX_ESC_HOLD:
            return "".join(out), text[index:]
        index += 1
    return "".join(out), ""


def normalize(text: str) -> str:
    """Flatten borders, control bytes and line wrapping into single spaces."""
    text = BOX_RE.sub(" ", text)
    text = CTRL_RE.sub(" ", text)
    return WS_RE.sub(" ", text)


def scan(text: str, now: datetime, default_tz: ZoneInfo) -> LimitHit | None:
    """Find the most recent limit message in a normalized buffer."""
    hit = None
    for trigger in TRIGGER_RE.finditer(text):
        window = text[trigger.start() : trigger.start() + WINDOW_CHARS]
        found = _parse_window(window, now, default_tz)
        if found is not None:
            hit = found
    return hit


def _parse_window(window: str, now: datetime, tz: ZoneInfo) -> LimitHit | None:
    match = ABSOLUTE_RE.search(window)
    if match:
        try:
            when = datetime(
                int(match["year"]),
                MONTHS[match["mon"].lower()[:3]],
                int(match["day"]),
                to_24h(int(match["hour"]), match["ampm"]),
                int(match["min"]),
                tzinfo=tz,
            )
        except ValueError:
            return None
        return LimitHit(when, "absolute", match.group(0))

    match = CLOCK_RE.search(window)
    if match:
        zone = get_tz(match["tz"]) if match["tz"] else tz
        hour = to_24h(int(match["hour"]), match["ampm"])
        minute = int(match["min"] or 0)
        weekday = WEEKDAYS[match["dow"].lower()[:3]] if match["dow"] else None
        if hour > 23 or minute > 59:
            return None
        when = next_occurrence(now, hour, minute, zone, weekday=weekday)
        return LimitHit(when, "clock", match.group(0))

    match = RELATIVE_RE.search(window)
    if match and (match["hours"] or match["mins"]):
        delta = timedelta(
            hours=int(match["hours"] or 0), minutes=int(match["mins"] or 0)
        )
        return LimitHit(now + delta, "relative", match.group(0))

    return None


def plausible(reset_at: datetime, now: datetime) -> bool:
    """Reject readings that cannot be a real rate-limit reset."""
    return -MAX_PAST <= (reset_at - now) <= MAX_HORIZON


SAMPLES = [
    "■ You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
    "visit https://chatgpt.com/codex/settings/usage to purchase more credits or try "
    "again at Jul 23rd, 2026 1:16 AM.",
    "You've hit your session limit · resets 6:20pm (America/Sao_Paulo)",
    "Claude usage limit reached. Your limit will reset at 4pm (America/Sao_Paulo).",
    "You've hit your weekly limit · resets Tue 9am",
    "5-hour limit reached ∙ resets 3:45pm",
    "You've hit your usage limit. Try again in 4 hours 32 minutes.",
]
