import unittest
from unittest import mock

from automode.agents import ping


class HeadlessArgvTests(unittest.TestCase):
    def test_claude_uses_print_mode(self):
        self.assertEqual(ping.headless_argv("claude", "hi"), ["claude", "-p", "hi"])

    def test_codex_uses_exec(self):
        self.assertEqual(ping.headless_argv("codex", "hi"), ["codex", "exec", "hi"])

    def test_unknown_agent_is_refused(self):
        with self.assertRaises(ValueError):
            ping.headless_argv("gemini", "oi")


class PlistTests(unittest.TestCase):
    def test_calendar_intervals_come_from_the_configured_times(self):
        plist = ping.build_plist(["05:00", "17:30"], "claude", "oi")
        self.assertEqual(
            plist["StartCalendarInterval"],
            [{"Hour": 5, "Minute": 0}, {"Hour": 17, "Minute": 30}],
        )

    def test_bad_times_are_dropped(self):
        plist = ping.build_plist(["05:00", "nao-e-hora"], "claude", "oi")
        self.assertEqual(plist["StartCalendarInterval"], [{"Hour": 5, "Minute": 0}])

    def test_no_usable_time_is_an_error_not_an_empty_schedule(self):
        with self.assertRaises(ValueError):
            ping.build_plist(["25:00"], "claude", "oi")

    def test_does_not_run_at_load(self):
        # Loading the agent must not fire a ping right now — that would open the
        # usage window at the wrong time, which is the whole thing we avoid.
        plist = ping.build_plist(["05:00"], "claude", "oi")
        self.assertFalse(plist["RunAtLoad"])

    def test_path_can_find_the_agents(self):
        plist = ping.build_plist(["05:00"], "claude", "oi")
        path = plist["EnvironmentVariables"]["PATH"]
        self.assertIn("/usr/bin", path)
        self.assertTrue(len(path.split(":")) >= 4)

    def test_prefers_the_installed_script(self):
        with mock.patch("shutil.which", return_value="/opt/homebrew/bin/automode"):
            plist = ping.build_plist(["05:00"], "claude", "oi")
        self.assertEqual(
            plist["ProgramArguments"],
            ["/opt/homebrew/bin/automode", "ping", "--agent", "claude", "--message", "oi"],
        )

    def test_falls_back_to_module_with_a_working_directory(self):
        # Without a cwd the module would not import and the 5am ping would fail
        # silently.
        with mock.patch("shutil.which", return_value=None):
            plist = ping.build_plist(["05:00"], "claude", "oi")
        self.assertIn("-m", plist["ProgramArguments"])
        self.assertIn("automode", plist["ProgramArguments"])
        self.assertTrue(plist["WorkingDirectory"])

    def test_message_is_carried_through(self):
        plist = ping.build_plist(["05:00"], "codex", "bom dia")
        self.assertIn("bom dia", plist["ProgramArguments"])


class WakeHintTests(unittest.TestCase):
    def test_suggests_waking_two_minutes_before_the_first_ping(self):
        self.assertEqual(ping._earliest(["05:00", "17:00"]), "04:58:00")

    def test_uses_the_earliest_slot_regardless_of_order(self):
        self.assertEqual(ping._earliest(["17:00", "06:30"]), "06:28:00")

    def test_does_not_wrap_past_midnight(self):
        self.assertEqual(ping._earliest(["00:01"]), "00:00:00")

    def test_no_times_no_hint(self):
        self.assertIsNone(ping._earliest([]))


if __name__ == "__main__":
    unittest.main()
