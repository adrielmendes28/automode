import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from automode.core import timeutil

SP = ZoneInfo("America/Sao_Paulo")
NY = ZoneInfo("America/New_York")


class To24hTests(unittest.TestCase):
    def test_am_pm_conversion(self):
        self.assertEqual(timeutil.to_24h(1, "am"), 1)
        self.assertEqual(timeutil.to_24h(1, "pm"), 13)

    def test_twelve_is_the_tricky_one(self):
        self.assertEqual(timeutil.to_24h(12, "am"), 0)
        self.assertEqual(timeutil.to_24h(12, "pm"), 12)


class NextOccurrenceTests(unittest.TestCase):
    def test_later_today(self):
        now = datetime(2026, 7, 16, 9, 0, tzinfo=SP)
        self.assertEqual(
            timeutil.next_occurrence(now, 18, 20, SP),
            datetime(2026, 7, 16, 18, 20, tzinfo=SP),
        )

    def test_already_passed_rolls_to_tomorrow(self):
        now = datetime(2026, 7, 16, 19, 0, tzinfo=SP)
        self.assertEqual(
            timeutil.next_occurrence(now, 18, 20, SP),
            datetime(2026, 7, 17, 18, 20, tzinfo=SP),
        )

    def test_within_slack_stays_today(self):
        now = datetime(2026, 7, 16, 18, 21, tzinfo=SP)
        self.assertEqual(
            timeutil.next_occurrence(now, 18, 20, SP),
            datetime(2026, 7, 16, 18, 20, tzinfo=SP),
        )

    def test_weekday_target(self):
        # Thursday -> next Tuesday
        now = datetime(2026, 7, 16, 14, 0, tzinfo=SP)
        self.assertEqual(
            timeutil.next_occurrence(now, 9, 0, SP, weekday=1),
            datetime(2026, 7, 21, 9, 0, tzinfo=SP),
        )

    def test_weekday_today_but_later(self):
        # Thursday 08:00, asking for Thursday 09:00 -> today
        now = datetime(2026, 7, 16, 8, 0, tzinfo=SP)
        self.assertEqual(
            timeutil.next_occurrence(now, 9, 0, SP, weekday=3),
            datetime(2026, 7, 16, 9, 0, tzinfo=SP),
        )

    def test_reading_is_wall_clock_across_dst(self):
        # US DST starts 2026-03-08. 9am the next morning is 9am on the clock,
        # which is 24h minus one hour of real elapsed time.
        now = datetime(2026, 3, 7, 12, 0, tzinfo=NY)
        target = timeutil.next_occurrence(now, 9, 0, NY)
        self.assertEqual(target.hour, 9)
        self.assertEqual(target.date(), datetime(2026, 3, 8).date())
        self.assertEqual(target.utcoffset().total_seconds(), -4 * 3600)


class ParseHhmmTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(timeutil.parse_hhmm("05:00"), (5, 0))
        self.assertEqual(timeutil.parse_hhmm(" 17:30 "), (17, 30))

    def test_invalid(self):
        for bad in ["", "5", "25:00", "12:60", "abc", "12:aa", "1:2:3"]:
            self.assertIsNone(timeutil.parse_hhmm(bad), bad)


class LocalTzTests(unittest.TestCase):
    def test_returns_a_usable_zone(self):
        self.assertIsNotNone(timeutil.get_tz(None))

    def test_bad_name_falls_back(self):
        self.assertIsNotNone(timeutil.get_tz("Not/AZone"))


if __name__ == "__main__":
    unittest.main()
