import copy
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from automode.core import config as configmod
from automode.controller import Controller

SP = ZoneInfo("America/Sao_Paulo")


class FakeClock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class FakeState:
    def __init__(self):
        self.fired = set()

    def ping_fired(self, key):
        return key in self.fired

    def mark_ping(self, key):
        self.fired.add(key)


class Harness:
    """A controller plus the wiring the pty runner would normally provide."""

    def __init__(self, start, **overrides):
        config = copy.deepcopy(configmod.DEFAULTS)
        config["timezone"] = "America/Sao_Paulo"
        config["notify"] = False
        ping = overrides.pop("ping", None)
        config.update(overrides)
        if ping:
            config["ping"].update(ping)
        self.clock = FakeClock(start)
        self.state = FakeState()
        self.logs = []
        self.typed = bytearray()
        self.controller = Controller(
            config,
            log=self.logs.append,
            state=self.state,
            clock=self.clock,
        )

    def output(self, text):
        self.controller.on_output(text.encode())

    def keypress(self, data=b"x"):
        self.controller.on_user_input(data)

    def tick(self):
        self.controller.tick(self.typed.extend)

    def run_for(self, seconds, step=1):
        for _ in range(int(seconds / step)):
            self.clock.advance(seconds=step)
            self.tick()

    @property
    def sent(self):
        return bytes(self.typed).decode()


LIMIT = "You've hit your session limit · resets 6:20pm (America/Sao_Paulo)"


class ContinueTests(unittest.TestCase):
    def test_types_continue_one_grace_after_the_reset(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        h.output(LIMIT)
        self.assertEqual(h.sent, "")

        h.run_for(21 * 60 + 5)  # 18:20 reset + 60s grace, plus the Enter delay
        self.assertEqual(h.sent, "continue\r")

    def test_nothing_happens_before_the_reset(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        h.output(LIMIT)
        h.run_for(19 * 60)
        self.assertEqual(h.sent, "")

    def test_redraws_do_not_queue_a_second_continue(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        for _ in range(50):  # the TUI repainting the same message
            h.clock.advance(seconds=1)
            h.output(LIMIT)
        h.run_for(25 * 60)
        self.assertEqual(h.sent, "continue\r")

    def test_auto_continue_off_types_nothing(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), auto_continue=False)
        h.output(LIMIT)
        h.run_for(30 * 60)
        self.assertEqual(h.sent, "")
        self.assertTrue(any("auto continue is off" in line for line in h.logs))

    def test_waits_while_you_are_typing(self):
        h = Harness(
            datetime(2026, 7, 16, 18, 0, tzinfo=SP),
            grace_seconds=60,
            idle_guard_seconds=10,
        )
        h.output(LIMIT)
        h.clock.advance(minutes=21)  # past the reset
        h.keypress()  # ...but you are at the keyboard
        h.tick()
        self.assertEqual(h.sent, "")

        h.run_for(30)  # you stop typing
        self.assertEqual(h.sent, "continue\r")

    def test_custom_message(self):
        h = Harness(
            datetime(2026, 7, 16, 18, 0, tzinfo=SP),
            grace_seconds=60,
            continue_message="segue",
        )
        h.output(LIMIT)
        h.run_for(25 * 60)
        self.assertEqual(h.sent, "segue\r")

    def test_a_new_limit_later_arms_again(self):
        h = Harness(datetime(2026, 7, 16, 12, 0, tzinfo=SP), grace_seconds=60)
        h.output("You've hit your session limit · resets 1:00pm")
        h.run_for(70 * 60)
        self.assertEqual(h.sent, "continue\r")

        h.output("You've hit your session limit · resets 6:00pm")
        h.run_for(5 * 60 * 60)
        self.assertEqual(h.sent, "continue\rcontinue\r")

    def test_message_split_across_reads(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        for chunk in ["You've hit your ", "session limit · rese", "ts 6:20pm"]:
            h.output(chunk)
        h.run_for(25 * 60)
        self.assertEqual(h.sent, "continue\r")

    def test_ansi_split_across_reads_does_not_break_detection(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        h.output("\x1b[31mYou've hit your session limit · resets 6:2")
        h.output("0pm\x1b[0m")
        h.run_for(25 * 60)
        self.assertEqual(h.sent, "continue\r")

    def test_nonsense_reset_is_ignored(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP))
        h.output("You've hit your usage limit. Try again at Jul 23rd, 2099 1:16 AM.")
        h.run_for(60 * 60)
        self.assertEqual(h.sent, "")


CLAUDE_MENU = (
    "You've hit your session limit · resets 6:20pm (America/Sao_Paulo) "
    "What do you want to do? "
    "❯ 1. Upgrade your plan "
    "2. Upgrade to Team plan "
    "3. Stop and wait for limit to reset"
)

CODEX_MENU = (
    "■ You've hit your usage limit. Upgrade to Pro or try again at "
    "Jul 16th, 2026 8:00 PM. "
    "Approaching rate limits Switch to gpt-5.4-mini for lower credit usage? "
    "1. Switch to gpt-5.4-mini "
    "› 2. Keep current model "
    "3. Keep current model (never show again)"
)


class BlockingPromptTests(unittest.TestCase):
    """The limit leaves the agent on a menu. `continue` typed there goes nowhere."""

    def test_answers_claude_menu_before_continuing(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        h.output(CLAUDE_MENU)
        h.run_for(22 * 60)
        self.assertEqual(h.sent, "3\rcontinue\r")

    def test_answers_codex_menu_before_continuing(self):
        h = Harness(datetime(2026, 7, 16, 19, 0, tzinfo=SP), grace_seconds=60)
        h.output(CODEX_MENU)
        h.run_for(70 * 60)
        self.assertEqual(h.sent, "2\rcontinue\r")

    def test_the_answer_comes_first_and_the_continue_waits(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        h.output(CLAUDE_MENU)
        h.clock.advance(minutes=21)
        h.tick()
        # The menu key goes out now; the message must not be glued to it.
        self.assertEqual(h.sent, "3")
        h.run_for(3)
        self.assertEqual(h.sent, "3\rcontinue\r")

    def test_no_menu_means_no_stray_keypress(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        h.output(LIMIT)  # limit message only, no menu
        h.run_for(22 * 60)
        self.assertEqual(h.sent, "continue\r")

    def test_does_not_answer_if_you_were_at_the_keyboard(self):
        # You came back and dealt with the menu yourself. Sending a number now
        # would type a stray "3" into a live prompt.
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        h.output(CLAUDE_MENU)
        h.clock.advance(minutes=5)
        h.keypress()  # you picked the option yourself
        h.run_for(20 * 60)
        self.assertEqual(h.sent, "continue\r")

    def test_can_be_turned_off(self):
        h = Harness(
            datetime(2026, 7, 16, 18, 0, tzinfo=SP),
            grace_seconds=60,
            answer_limit_prompt=False,
        )
        h.output(CLAUDE_MENU)
        h.run_for(22 * 60)
        self.assertEqual(h.sent, "continue\r")

    def test_it_is_logged(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        h.output(CLAUDE_MENU)
        h.run_for(22 * 60)
        self.assertTrue(
            any("limit menu" in line and "option 3" in line for line in h.logs),
            h.logs,
        )


class PingTests(unittest.TestCase):
    def config(self, **kwargs):
        base = {"enabled": True, "times": ["05:00"], "idle_seconds": 20}
        base.update(kwargs)
        return base

    def test_fires_at_the_scheduled_time_when_idle(self):
        h = Harness(datetime(2026, 7, 16, 4, 59, tzinfo=SP), ping=self.config())
        h.run_for(120)
        self.assertEqual(h.sent, "hi\r")

    def test_does_not_fire_before_the_time(self):
        h = Harness(datetime(2026, 7, 16, 4, 0, tzinfo=SP), ping=self.config())
        h.run_for(30 * 60)
        self.assertEqual(h.sent, "")

    def test_fires_only_once_per_day(self):
        h = Harness(datetime(2026, 7, 16, 4, 59, tzinfo=SP), ping=self.config())
        h.run_for(20 * 60)
        self.assertEqual(h.sent, "hi\r")

    def test_waits_for_a_quiet_session(self):
        h = Harness(datetime(2026, 7, 16, 4, 59, tzinfo=SP), ping=self.config())
        h.clock.advance(minutes=2)
        h.output("agent is busy working")  # not idle
        h.tick()
        self.assertEqual(h.sent, "")

        h.run_for(60)  # agent goes quiet
        self.assertEqual(h.sent, "hi\r")

    def test_catch_up_after_the_machine_slept_through_it(self):
        # Wakes at 05:10, ten minutes late, still inside the catch-up window.
        h = Harness(
            datetime(2026, 7, 16, 5, 10, tzinfo=SP),
            ping=self.config(catchup_minutes=30),
        )
        h.run_for(60)
        self.assertEqual(h.sent, "hi\r")

    def test_gives_up_outside_the_catch_up_window(self):
        h = Harness(
            datetime(2026, 7, 16, 7, 0, tzinfo=SP),
            ping=self.config(catchup_minutes=30),
        )
        h.run_for(60)
        self.assertEqual(h.sent, "")

    def test_already_fired_is_remembered(self):
        h = Harness(datetime(2026, 7, 16, 5, 10, tzinfo=SP), ping=self.config())
        h.state.fired.add("2026-07-16 05:00")
        h.run_for(60)
        self.assertEqual(h.sent, "")

    def test_disabled_does_nothing(self):
        h = Harness(
            datetime(2026, 7, 16, 4, 59, tzinfo=SP), ping=self.config(enabled=False)
        )
        h.run_for(20 * 60)
        self.assertEqual(h.sent, "")

    def test_two_slots_both_fire(self):
        h = Harness(
            datetime(2026, 7, 16, 4, 59, tzinfo=SP),
            ping=self.config(times=["05:00", "17:00"]),
        )
        h.run_for(60 * 60, step=10)
        self.assertEqual(h.sent, "hi\r")
        h.run_for(12 * 60 * 60, step=10)
        self.assertEqual(h.sent, "hi\rhi\r")

    def test_invalid_time_is_skipped_not_crashed(self):
        h = Harness(
            datetime(2026, 7, 16, 4, 59, tzinfo=SP),
            ping=self.config(times=["nao-e-hora", "05:00"]),
        )
        h.run_for(120)
        self.assertEqual(h.sent, "hi\r")

    def test_ping_does_not_collide_with_a_pending_continue(self):
        h = Harness(
            datetime(2026, 7, 16, 4, 50, tzinfo=SP),
            grace_seconds=60,
            ping=self.config(),
        )
        h.output("You've hit your session limit · resets 6:00am")
        h.run_for(15 * 60)  # 05:00 passes while a continue is armed
        self.assertEqual(h.sent, "")


class TimeoutTests(unittest.TestCase):
    def test_reports_time_until_the_next_action(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        self.assertEqual(h.controller.next_timeout(), 1.0)
        h.output(LIMIT)
        # 20 minutes to the reset, but capped by the 1s poll floor
        self.assertEqual(h.controller.next_timeout(), 1.0)

    def test_never_negative(self):
        h = Harness(datetime(2026, 7, 16, 18, 0, tzinfo=SP), grace_seconds=60)
        h.output(LIMIT)
        h.clock.advance(hours=2)
        self.assertGreaterEqual(h.controller.next_timeout(), 0.0)


if __name__ == "__main__":
    unittest.main()
