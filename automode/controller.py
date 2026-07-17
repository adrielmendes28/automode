"""Decide what to type into the wrapped session, and when.

The controller sees a copy of everything the agent prints and every key you
press. From that it does two things: arm a `continue` for the moment the usage
limit resets (auto continue), and fire the scheduled pings (auto ping).

Time comes from an injected clock so the schedule can be tested without
waiting five hours for a real one.
"""

from __future__ import annotations

import codecs
from datetime import datetime, timedelta
from typing import Any, Callable

from .agents import detect, dialogs
from .core.log import Logger, notify
from .core.state import State
from .core.timeutil import get_tz, parse_hhmm

BUFFER_CHARS = 8000
SCAN_INTERVAL = timedelta(milliseconds=250)
# Some TUIs drop an Enter that arrives glued to the text; let the input land first.
ENTER_DELAY = timedelta(milliseconds=250)
# How long a message stays "already seen" after it leaves the screen.
SEEN_TTL = timedelta(seconds=120)
SEEN_PRUNE = timedelta(hours=1)
MIN_LEAD = timedelta(seconds=2)
# Time for the agent to dismiss its limit menu before we type into the prompt.
PROMPT_SETTLE = timedelta(milliseconds=750)


class Controller:
    """Watches one wrapped agent session."""

    def __init__(
        self,
        config: dict[str, Any],
        log: Logger | None = None,
        state: State | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.config = config
        self._tz_name = config.get("timezone") or None
        self._tz = get_tz(self._tz_name)
        self.log = log or Logger(enabled=True)
        self.state = state or State()
        self._clock = clock or (lambda: datetime.now(self.tz))

        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._esc_leftover = ""
        self._buffer = ""
        self._unscanned = False
        self._seen: dict[str, datetime] = {}

        now = self._clock()
        self._last_scan = now - SCAN_INTERVAL
        self._last_input = now
        self._last_output = now
        self._fire_at: datetime | None = None
        self._fire_reason = ""
        self._armed_at: datetime | None = None
        self._queue: list[tuple[datetime, bytes]] = []

    @property
    def tz(self):
        """The configured zone, re-read because the menu can change it mid-session."""
        name = self.config.get("timezone") or None
        if name != self._tz_name:
            self._tz_name = name
            self._tz = get_tz(name)
        return self._tz

    # ---- stream side -------------------------------------------------

    def on_output(self, data: bytes) -> None:
        now = self._clock()
        self._last_output = now
        text = self._decoder.decode(data)
        clean, self._esc_leftover = detect.strip_ansi_stream(self._esc_leftover + text)
        if not clean:
            return
        self._buffer = (self._buffer + detect.normalize(clean))[-BUFFER_CHARS:]
        self._unscanned = True
        self._maybe_scan(now)

    def _maybe_scan(self, now: datetime) -> None:
        """Scan at most every SCAN_INTERVAL, but never drop a pending one.

        Throttling matters because the TUI repaints constantly. Deferring
        rather than skipping matters because the last chunk of a message may
        land inside the throttle window and be the last thing ever printed.
        """
        if not self._unscanned or now - self._last_scan < SCAN_INTERVAL:
            return
        self._last_scan = now
        self._unscanned = False
        self._scan(now)

    def on_user_input(self, _data: bytes) -> None:
        self._last_input = self._clock()

    # ---- clock side --------------------------------------------------

    def next_timeout(self) -> float:
        """Seconds until the next thing we have to do."""
        now = self._clock()
        waits = [1.0]
        if self._unscanned:
            waits.append(SCAN_INTERVAL.total_seconds())
        if self._queue:
            waits.append((self._queue[0][0] - now).total_seconds())
        if self._fire_at is not None:
            waits.append((self._fire_at - now).total_seconds())
        return max(min(waits), 0.0)

    def tick(self, inject: Callable[[bytes], None]) -> None:
        now = self._clock()
        self._maybe_scan(now)

        if self._fire_at is not None and now >= self._fire_at:
            self._fire_continue(now)

        self._check_pings(now)

        while self._queue and self._queue[0][0] <= now:
            _, payload = self._queue.pop(0)
            inject(payload)

    # ---- limit detection ---------------------------------------------

    def _scan(self, now: datetime) -> None:
        hit = detect.scan(self._buffer, now, self.tz)
        if hit is None or not detect.plausible(hit.reset_at, now):
            return

        # The message sits on screen and is redrawn constantly. Refresh the
        # sighting every time, but only act on the first one — or on one that
        # reappears after the screen has been clear of it for a while.
        key = hit.reset_at.isoformat()
        previously = self._seen.get(key)
        self._seen[key] = now
        self._prune_seen(now)
        if previously is not None and now - previously < SEEN_TTL:
            return

        self._arm(hit, now)

    def _prune_seen(self, now: datetime) -> None:
        if len(self._seen) > 32:
            self._seen = {
                key: at for key, at in self._seen.items() if now - at < SEEN_PRUNE
            }

    def _arm(self, hit: detect.LimitHit, now: datetime) -> None:
        local = hit.reset_at.astimezone(self.tz)
        self.log(
            f"limit detected ({hit.kind}): {hit.raw!r} -> resets {local:%Y-%m-%d %H:%M %Z}"
        )
        if not self.config.get("auto_continue", True):
            self.log("auto continue is off — standing down")
            return

        grace = timedelta(seconds=int(self.config.get("grace_seconds", 60)))
        fire_at = max(hit.reset_at + grace, now + MIN_LEAD)
        self._fire_at = fire_at
        self._fire_reason = f"reset {local:%H:%M}"
        self._armed_at = now

        wait = fire_at - now
        message = self.config.get("continue_message", "continue")
        self.log(
            f"queued {message!r} for {fire_at.astimezone(self.tz):%Y-%m-%d %H:%M:%S} "
            f"(in {humanize(wait)})"
        )
        if self.config.get("notify", True):
            notify(
                "automode",
                f"Limit until {local:%H:%M}. Continuing on my own in {humanize(wait)}.",
            )

    def _fire_continue(self, now: datetime) -> None:
        idle_guard = timedelta(seconds=float(self.config.get("idle_guard_seconds", 5)))
        if now - self._last_input < idle_guard:
            # You are typing right now; do not shove text into your prompt.
            self._fire_at = now + idle_guard
            return

        message = self.config.get("continue_message", "continue")
        delay = self._answer_blocking_prompt(now)
        self._enqueue(message, now + delay)
        self._fire_at = None
        self._armed_at = None
        self.log(f"sent {message!r} ({self._fire_reason})")
        if self.config.get("notify", True):
            notify("automode", f"Limit is back — sent {message!r}.")
        # Drop the stale screen text so the same message cannot re-arm us.
        self._buffer = ""

    def _answer_blocking_prompt(self, now: datetime) -> timedelta:
        """Dismiss the limit menu, if the agent is still sitting on it.

        Returns how long to wait before typing the continue message.

        We only do this when you have not touched the keyboard since the limit
        was detected. If you have, you were here and presumably answered it
        yourself — and pressing a number into a live prompt would send a stray
        message to the agent.
        """
        if not self.config.get("answer_limit_prompt", True):
            return timedelta()
        if self._armed_at is not None and self._last_input > self._armed_at:
            return timedelta()
        answer = dialogs.find(self._buffer)
        if answer is None:
            return timedelta()
        self._enqueue(answer.key, now)
        self.log(f"limit menu ({answer.name}): chose option {answer.key}")
        return PROMPT_SETTLE

    # ---- scheduled pings ---------------------------------------------

    def _check_pings(self, now: datetime) -> None:
        ping = self.config.get("ping", {})
        if not ping.get("enabled") or not ping.get("times"):
            return
        if self._queue or self._fire_at is not None:
            return  # something else is already mid-flight

        catchup = timedelta(minutes=int(ping.get("catchup_minutes", 30)))
        idle_needed = timedelta(seconds=float(ping.get("idle_seconds", 20)))
        local = now.astimezone(self.tz)

        for entry in ping["times"]:
            parsed = parse_hhmm(str(entry))
            if parsed is None:
                continue
            hour, minute = parsed
            # Yesterday too: the machine may have slept through a late-night slot.
            for day_offset in (0, -1):
                target = (local + timedelta(days=day_offset)).replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
                if now < target or now - target > catchup:
                    continue
                key = f"{target:%Y-%m-%d} {entry}"
                if self.state.ping_fired(key):
                    continue
                idle = min(now - self._last_output, now - self._last_input)
                if idle < idle_needed:
                    return  # session is busy; try again on the next tick
                message = ping.get("message", "oi")
                self._enqueue(message, now)
                self.state.mark_ping(key)
                self.log(f"auto ping {entry}: sent {message!r} into the session")
                return

    # ---- typing ------------------------------------------------------

    def _enqueue(self, message: str, now: datetime) -> None:
        self._queue.append((now, message.encode("utf-8")))
        self._queue.append((now + ENTER_DELAY, b"\r"))


def humanize(delta: timedelta) -> str:
    seconds = max(int(delta.total_seconds()), 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}"
    if minutes:
        return f"{minutes}min"
    return f"{secs}s"
