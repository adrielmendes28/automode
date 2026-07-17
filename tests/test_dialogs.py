import unittest

from automode.agents import detect, dialogs


class FindTests(unittest.TestCase):
    def test_every_known_prompt_is_answered_correctly(self):
        for name, expected_key, sample in dialogs.SAMPLES:
            answer = dialogs.find(detect.normalize(sample))
            self.assertIsNotNone(answer, name)
            self.assertEqual(answer.name, name)
            self.assertEqual(answer.key, expected_key, name)

    def test_claude_menu_picks_wait_not_upgrade(self):
        answer = dialogs.find(
            detect.normalize(
                "What do you want to do? "
                "❯ 1. Upgrade your plan "
                "2. Upgrade to Team plan "
                "3. Stop and wait for limit to reset"
            )
        )
        self.assertEqual(answer.key, "3")

    def test_claude_option_number_is_read_not_assumed(self):
        # If the menu is ever reordered, we must follow the text.
        answer = dialogs.find(
            detect.normalize(
                "What do you want to do? "
                "1. Stop and wait for limit to reset "
                "2. Upgrade your plan"
            )
        )
        self.assertEqual(answer.key, "1")

    def test_codex_keeps_the_current_model(self):
        answer = dialogs.find(detect.normalize(dialogs.SAMPLES[1][2]))
        self.assertEqual(answer.key, "2")

    def test_codex_never_show_again_is_not_mistaken_for_keep(self):
        # "3. Keep current model (never show again)" also contains "Keep
        # current model" — picking it would silence future warnings forever.
        answer = dialogs.find(detect.normalize(dialogs.SAMPLES[1][2]))
        self.assertNotEqual(answer.key, "3")

    def test_the_menu_wrapped_in_a_tui_frame(self):
        raw = (
            "\x1b[2J╭────────────────────────────╮\r\n"
            "│ \x1b[1mWhat do you want to do?\x1b[0m    │\r\n"
            "│ ❯ 1. Upgrade your plan        │\r\n"
            "│   2. Upgrade to Team plan     │\r\n"
            "│   3. Stop and wait for limit  │\r\n"
            "│      to reset                 │\r\n"
            "╰────────────────────────────╯\r\n"
        )
        clean, _ = detect.strip_ansi_stream(raw)
        answer = dialogs.find(detect.normalize(clean))
        self.assertIsNotNone(answer, "nao achou o menu quebrado pela moldura")
        self.assertEqual(answer.key, "3")

    def test_context_is_required(self):
        # The words alone, with no menu around them, must not trigger.
        self.assertIsNone(dialogs.find("3. Stop and wait for limit to reset"))
        self.assertIsNone(dialogs.find("2. Keep current model"))

    def test_ordinary_screen_text_is_not_a_prompt(self):
        for text in [
            "",
            "the model is fine, keep current model settings",
            "What do you want to do? 1. Deploy 2. Rollback",
            "You've hit your session limit · resets 6:20pm",
        ]:
            self.assertIsNone(dialogs.find(text), text)


if __name__ == "__main__":
    unittest.main()
