import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from automode.agents import detect

SP = ZoneInfo("America/Sao_Paulo")


def at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=SP)


class StripAnsiTests(unittest.TestCase):
    def test_removes_colors_and_cursor_moves(self):
        clean, leftover = detect.strip_ansi_stream("\x1b[31mred\x1b[0m\x1b[2J done")
        self.assertEqual(clean, "red done")
        self.assertEqual(leftover, "")

    def test_holds_back_sequence_split_across_reads(self):
        clean, leftover = detect.strip_ansi_stream("ok\x1b[3")
        self.assertEqual(clean, "ok")
        self.assertEqual(leftover, "\x1b[3")
        # the rest of the sequence arrives next read
        clean, leftover = detect.strip_ansi_stream(leftover + "1mred")
        self.assertEqual(clean, "red")
        self.assertEqual(leftover, "")

    def test_drops_stray_esc_that_never_terminates(self):
        clean, leftover = detect.strip_ansi_stream("\x1b" + "x" * 60)
        self.assertEqual(clean, "x" * 60)
        self.assertEqual(leftover, "")

    def test_strips_window_title_sequence(self):
        clean, _ = detect.strip_ansi_stream("\x1b]0;my title\x07hello")
        self.assertEqual(clean, "hello")


class NormalizeTests(unittest.TestCase):
    def test_flattens_box_borders_and_wrapping(self):
        raw = (
            "╭──────────────╮\r\n"
            "│ You've hit your usage limit. Try   │\r\n"
            "│ again in 2 hours 5 minutes.        │\r\n"
            "╰──────────────╯\r\n"
        )
        self.assertEqual(
            detect.normalize(raw),
            " You've hit your usage limit. Try again in 2 hours 5 minutes. ",
        )


class ScanTests(unittest.TestCase):
    def test_codex_clock_exact_message(self):
        text = (
            "■ You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
            "visit https://chatgpt.com/settings/usage to purchase more credits or try "
            "again at 4:14 AM."
        )
        hit = detect.scan(detect.normalize(text), at(2026, 7, 16, 3), SP)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.kind, "clock")
        self.assertEqual(hit.reset_at, at(2026, 7, 16, 4, 14))

    def test_codex_clock_variants(self):
        for reading, hour, minute in [
            ("4:14 AM", 4, 14),
            ("4:14AM", 4, 14),
            ("4:14 am", 4, 14),
            ("4:14am", 4, 14),
            ("4:14 PM", 16, 14),
            ("4:14PM", 16, 14),
            ("4:14 pm", 16, 14),
            ("4:14pm", 16, 14),
            ("12:00 PM", 12, 0),
            ("12:00AM", 0, 0),
        ]:
            with self.subTest(reading=reading):
                hit = detect.scan(
                    f"You've hit your usage limit. try again at {reading}.",
                    at(2026, 7, 16, 0), SP,
                )
                self.assertIsNotNone(hit)
                self.assertEqual(hit.kind, "clock")
                self.assertEqual(hit.reset_at, at(2026, 7, 16, hour, minute))

    def test_codex_clock_rollover_and_recent_reset(self):
        for now, expected in [
            (at(2026, 7, 16, 23, 50), at(2026, 7, 17, 4, 14)),
            (at(2026, 7, 16, 4, 15), at(2026, 7, 16, 4, 14)),
            (at(2026, 7, 16, 4, 16), at(2026, 7, 16, 4, 14)),
            (at(2026, 7, 16, 4, 17), at(2026, 7, 17, 4, 14)),
        ]:
            with self.subTest(now=now):
                hit = detect.scan(
                    "You've hit your usage limit. Try again at 4:14AM.", now, SP
                )
                self.assertIsNotNone(hit)
                self.assertEqual(hit.reset_at, expected)

    def test_codex_clock_uses_default_timezone(self):
        hit = detect.scan(
            "You've hit your usage limit. Try again at 4:14AM.",
            at(2026, 7, 16, 3), ZoneInfo("UTC"),
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit.reset_at, datetime(2026, 7, 17, 4, 14, tzinfo=ZoneInfo("UTC")))

    def test_codex_clock_wrapped_with_ansi(self):
        raw = (
            "\x1b[2J\x1b[H╭─────────────────────────────╮\r\n"
            "│ \x1b[31m■ You’ve hit your usage limit.\x1b[0m │\r\n"
            "│ Upgrade to Pro (https://chatgpt.com/explore/pro), │\r\n"
            "│ visit https://chatgpt.com/settings/usage to │\r\n"
            "│ purchase more credits or try │\r\n"
            "│ again at \x1b[1m4:14\x1b[0m │\r\n"
            "│ AM. │\r\n"
            "╰─────────────────────────────╯\r\n"
        )
        clean, leftover = detect.strip_ansi_stream(raw)
        self.assertEqual(leftover, "")
        hit = detect.scan(detect.normalize(clean), at(2026, 7, 16, 3), SP)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.reset_at, at(2026, 7, 16, 4, 14))

    def test_codex_clock_requires_trigger_and_valid_minutes(self):
        for text in [
            "Please try again at 4:14 AM.",
            "You've hit your usage limit. Try again at 4:60 AM.",
            "You've hit your usage limit. Try again at 4:99AM.",
        ]:
            with self.subTest(text=text):
                self.assertIsNone(detect.scan(text, at(2026, 7, 16, 3), SP))

    def test_absolute_date_takes_precedence_over_clock(self):
        hit = detect.scan(
            "You've hit your usage limit. Try again at 4:14 AM. "
            "Try again at Jul 23rd, 2026 1:16 AM.",
            at(2026, 7, 16, 3), SP,
        )
        self.assertEqual(hit.kind, "absolute")
        self.assertEqual(hit.reset_at, at(2026, 7, 23, 1, 16))

    def test_codex_absolute_date(self):
        now = at(2026, 7, 16, 20, 0)
        hit = detect.scan(detect.normalize(detect.SAMPLES[0]), now, SP)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.kind, "absolute")
        self.assertEqual(hit.reset_at, at(2026, 7, 23, 1, 16))

    def test_claude_session_limit_with_timezone(self):
        now = at(2026, 7, 16, 14, 30)
        hit = detect.scan(detect.normalize(detect.SAMPLES[1]), now, SP)
        self.assertEqual(hit.kind, "clock")
        self.assertEqual(hit.reset_at, at(2026, 7, 16, 18, 20))

    def test_claude_will_reset_at_variant(self):
        now = at(2026, 7, 16, 14, 30)
        hit = detect.scan(detect.normalize(detect.SAMPLES[2]), now, SP)
        self.assertEqual(hit.reset_at, at(2026, 7, 16, 16, 0))

    def test_weekly_limit_with_weekday(self):
        # 2026-07-16 is a Thursday; next Tuesday is the 21st.
        now = at(2026, 7, 16, 14, 30)
        hit = detect.scan(detect.normalize(detect.SAMPLES[3]), now, SP)
        self.assertEqual(hit.reset_at, at(2026, 7, 21, 9, 0))

    def test_five_hour_limit_without_timezone(self):
        now = at(2026, 7, 16, 13, 0)
        hit = detect.scan(detect.normalize(detect.SAMPLES[4]), now, SP)
        self.assertEqual(hit.reset_at, at(2026, 7, 16, 15, 45))

    def test_relative_wording(self):
        now = at(2026, 7, 16, 13, 0)
        hit = detect.scan(detect.normalize(detect.SAMPLES[5]), now, SP)
        self.assertEqual(hit.kind, "relative")
        self.assertEqual(hit.reset_at, now + timedelta(hours=4, minutes=32))

    def test_clock_reading_already_past_rolls_to_tomorrow(self):
        now = at(2026, 7, 16, 23, 50)
        hit = detect.scan(
            detect.normalize("You've hit your session limit · resets 12:20am"), now, SP
        )
        self.assertEqual(hit.reset_at, at(2026, 7, 17, 0, 20))

    def test_noon_and_midnight_are_not_swapped(self):
        now = at(2026, 7, 16, 6, 0)
        hit = detect.scan(
            detect.normalize("session limit reached · resets 12:00pm"), now, SP
        )
        self.assertEqual(hit.reset_at, at(2026, 7, 16, 12, 0))

    def test_message_just_barely_past_counts_as_now(self):
        # The agent prints the message a beat before the clock rolls over; it
        # must not be read as the same time tomorrow.
        now = at(2026, 7, 16, 18, 21)
        hit = detect.scan(
            detect.normalize("You've hit your session limit · resets 6:20pm"), now, SP
        )
        self.assertEqual(hit.reset_at, at(2026, 7, 16, 18, 20))

    def test_no_trigger_means_no_hit(self):
        now = at(2026, 7, 16, 14, 0)
        text = detect.normalize("the meeting resets 6:20pm and then we ship")
        self.assertIsNone(detect.scan(text, now, SP))

    def test_trigger_without_a_time_is_ignored(self):
        now = at(2026, 7, 16, 14, 0)
        text = detect.normalize("You've hit your usage limit. Upgrade to Pro.")
        self.assertIsNone(detect.scan(text, now, SP))

    def test_time_too_far_from_trigger_is_ignored(self):
        now = at(2026, 7, 16, 14, 0)
        text = detect.normalize(
            "You've hit your usage limit." + " filler" * 120 + " resets 6:20pm"
        )
        self.assertIsNone(detect.scan(text, now, SP))

    def test_finds_message_wrapped_inside_the_tui_frame(self):
        now = at(2026, 7, 16, 14, 0)
        raw = (
            "\x1b[2J\x1b[H╭────────────────────────────────╮\r\n"
            "│ \x1b[31m■\x1b[0m You've hit your usage limit.  │\r\n"
            "│ visit https://chatgpt.com/codex/settings/usage to    │\r\n"
            "│ purchase more credits or try again at Jul 23rd,      │\r\n"
            "│ 2026 1:16 AM.                                        │\r\n"
            "╰────────────────────────────────╯\r\n"
        )
        clean, _ = detect.strip_ansi_stream(raw)
        hit = detect.scan(detect.normalize(clean), now, SP)
        self.assertEqual(hit.reset_at, at(2026, 7, 23, 1, 16))

    def test_latest_message_on_screen_wins(self):
        now = at(2026, 7, 16, 10, 0)
        text = detect.normalize(
            "You've hit your session limit · resets 11:00am ... scrollback ... "
            "You've hit your session limit · resets 3:00pm"
        )
        hit = detect.scan(text, now, SP)
        self.assertEqual(hit.reset_at, at(2026, 7, 16, 15, 0))


class PlausibleTests(unittest.TestCase):
    def test_accepts_a_normal_reset(self):
        now = at(2026, 7, 16, 14, 0)
        self.assertTrue(detect.plausible(now + timedelta(hours=5), now))

    def test_rejects_far_future(self):
        now = at(2026, 7, 16, 14, 0)
        self.assertFalse(detect.plausible(now + timedelta(days=400), now))

    def test_rejects_stale_past(self):
        now = at(2026, 7, 16, 14, 0)
        self.assertFalse(detect.plausible(now - timedelta(days=2), now))


if __name__ == "__main__":
    unittest.main()
