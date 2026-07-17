"""Changes made in the Alt+G menu must reach the running session."""

import copy
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from automode.core import config as configmod
from automode.controller import Controller
from automode.terminal.overlay import Overlay
from tests.test_controller import FakeClock, FakeState, Harness

SP = ZoneInfo("America/Sao_Paulo")


class LiveConfigTests(unittest.TestCase):
    def test_menu_edits_land_on_the_dict_the_controller_reads(self):
        config = copy.deepcopy(configmod.DEFAULTS)
        config["timezone"] = "America/Sao_Paulo"
        config["notify"] = False
        clock = FakeClock(datetime(2026, 7, 16, 18, 0, tzinfo=SP))
        typed = bytearray()
        controller = Controller(config, log=lambda _m: None, state=FakeState(), clock=clock)
        overlay = Overlay(config, b"\x1bg")

        # You open the menu and turn auto-continue off.
        overlay.enter()
        overlay.menu.config["auto_continue"] = False
        overlay.menu.done = True
        overlay.leave()

        controller.on_output(b"You've hit your session limit resets 6:20pm")
        for _ in range(30 * 60):
            clock.advance(seconds=1)
            controller.tick(typed.extend)
        self.assertEqual(bytes(typed), b"")

    def test_timezone_change_is_picked_up_without_restarting(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        self.assertEqual(str(h.controller.tz), "America/Sao_Paulo")
        h.controller.config["timezone"] = "UTC"
        self.assertEqual(str(h.controller.tz), "UTC")

    def test_grace_change_applies_to_the_next_limit(self):
        h = Harness(datetime(2026, 7, 16, 12, 0, tzinfo=SP), grace_seconds=60)
        h.controller.config["grace_seconds"] = 5
        h.output("You've hit your session limit · resets 1:00pm")
        h.clock.advance(minutes=60)  # 13:00 exactly
        h.tick()
        self.assertEqual(h.sent, "")
        h.run_for(10)  # only 5s of grace now, not 60
        self.assertEqual(h.sent, "continue\r")


if __name__ == "__main__":
    unittest.main()
