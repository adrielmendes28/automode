import copy
import re
import unittest

from automode.core import config as configmod
from automode.terminal.menu import Menu
from automode.terminal.overlay import Overlay, parse_hotkey, parse_hotkeys
from automode.terminal.theme import BOLD, CLAUDE, CODEX, NOBOLD, for_agent


def base_config():
    config = copy.deepcopy(configmod.DEFAULTS)
    config["timezone"] = "America/Sao_Paulo"
    return config


class ParseHotkeyTests(unittest.TestCase):
    def test_alt_is_esc_prefixed(self):
        self.assertEqual(parse_hotkey("alt+g"), b"\x1bg")
        self.assertEqual(parse_hotkey("Alt+G"), b"\x1bg")
        self.assertEqual(parse_hotkey("meta+k"), b"\x1bk")

    def test_ctrl_is_a_control_byte(self):
        self.assertEqual(parse_hotkey("ctrl+g"), b"\x07")
        self.assertEqual(parse_hotkey("ctrl+o"), b"\x0f")

    def test_rejects_nonsense(self):
        for bad in ["", "alt+", "alt+gg", "hyper+g", "shift+ctrl+g", "+"]:
            self.assertIsNone(parse_hotkey(bad), bad)


class MultipleHotkeyTests(unittest.TestCase):
    def test_the_default_accepts_both_spellings(self):
        keys = parse_hotkeys(configmod.DEFAULTS["hotkey"])
        self.assertIn(b"\x07", keys)  # ctrl+g — chega em qualquer terminal
        self.assertIn(b"\x1bg", keys)  # alt+g — so se o terminal mandar Meta

    def test_either_key_opens_the_menu(self):
        overlay = Overlay(base_config(), parse_hotkeys("ctrl+g, alt+g"))
        self.assertTrue(overlay.matches_hotkey(b"\x07"))
        self.assertTrue(overlay.matches_hotkey(b"\x1bg"))

    def test_junk_entries_are_dropped_not_fatal(self):
        self.assertEqual(parse_hotkeys("ctrl+g, banana, alt+g"), [b"\x07", b"\x1bg"])

    def test_duplicates_collapse(self):
        self.assertEqual(parse_hotkeys("ctrl+g, ctrl+g"), [b"\x07"])

    def test_all_nonsense_means_no_menu(self):
        self.assertEqual(parse_hotkeys("banana, hyper+z"), [])


class CloseFlowTests(unittest.TestCase):
    """Opening is useless if you cannot get back to the agent."""

    def setUp(self):
        self.overlay = Overlay(base_config(), parse_hotkeys("ctrl+g, alt+g"))

    def _open(self):
        self.overlay.enter((24, 80))
        self.assertTrue(self.overlay.open)

    def test_q_closes(self):
        self._open()
        self.overlay.handle(b"q")
        self.assertTrue(self.overlay.done)

    def test_escape_closes(self):
        self._open()
        self.overlay.handle(b"\x1b")
        self.assertTrue(self.overlay.done)

    def test_the_hotkey_itself_closes(self):
        # Whatever opened it should close it — that is what everyone tries first.
        self._open()
        self.overlay.handle(b"\x07")
        self.assertTrue(self.overlay.done)

    def test_ctrl_c_closes(self):
        self._open()
        self.overlay.handle(b"\x03")
        self.assertTrue(self.overlay.done)

    def test_closing_hands_the_screen_back_and_reopens_cleanly(self):
        self._open()
        self.overlay.handle(b"q")
        restored = self.overlay.leave()
        self.assertIn(b"\x1b[?1049l", restored)  # sai da tela alternativa
        self.assertIn(b"\x1b[?25h", restored)  # cursor de volta
        self.assertFalse(self.overlay.open)
        # e da pra abrir de novo
        self.assertTrue(self.overlay.matches_hotkey(b"\x07"))
        self.overlay.enter((24, 80))
        self.assertTrue(self.overlay.open)
        self.assertFalse(self.overlay.done)

    def test_arrow_keys_do_not_close_it(self):
        self._open()
        for arrow in [b"\x1b[A", b"\x1b[B", b"\x1b[C", b"\x1b[D"]:
            self.overlay.handle(arrow)
            self.assertFalse(self.overlay.done, arrow)

    def test_typing_in_a_field_does_not_close_it(self):
        self._open()
        menu = self.overlay.menu
        menu.cursor = next(
            i for i, row in enumerate(menu.rows) if row.path == ("continue_message",)
        )
        self.overlay.handle(b"\r")  # entra em edicao
        self.overlay.handle(b"q")
        self.assertFalse(self.overlay.done)
        self.overlay.handle(b"\x1b")  # esc sai da edicao...
        self.assertFalse(self.overlay.done)
        self.overlay.handle(b"\x1b")  # ...e so entao fecha o menu
        self.assertTrue(self.overlay.done)


class HotkeyMatchTests(unittest.TestCase):
    def setUp(self):
        self.overlay = Overlay(base_config(), b"\x1bg")

    def test_alt_g_arrives_as_one_chunk_and_opens(self):
        self.assertTrue(self.overlay.matches_hotkey(b"\x1bg"))

    def test_escape_alone_does_not_open(self):
        # Esc is how you interrupt claude — it must reach the agent.
        self.assertFalse(self.overlay.matches_hotkey(b"\x1b"))

    def test_escape_then_g_typed_by_a_human_does_not_open(self):
        # Separate reads: the human pressed Esc, then later typed g.
        self.assertFalse(self.overlay.matches_hotkey(b"\x1b"))
        self.assertFalse(self.overlay.matches_hotkey(b"g"))

    def test_arrow_keys_do_not_open(self):
        for arrow in [b"\x1b[A", b"\x1b[B", b"\x1b[C", b"\x1b[D"]:
            self.assertFalse(self.overlay.matches_hotkey(arrow))

    def test_a_paste_containing_the_hotkey_does_not_open(self):
        self.assertFalse(self.overlay.matches_hotkey(b"\x1bg mais um monte de texto"))

    def test_does_not_reopen_while_already_open(self):
        self.overlay.enter()
        self.assertFalse(self.overlay.matches_hotkey(b"\x1bg"))


class AltScreenTrackingTests(unittest.TestCase):
    def setUp(self):
        self.overlay = Overlay(base_config(), b"\x1bg")

    def test_starts_assuming_the_agent_is_on_the_main_screen(self):
        self.assertFalse(self.overlay.child_in_alt)

    def test_notices_the_agent_entering_the_alternate_screen(self):
        self.overlay.track_output(b"\x1b[?1049hhello")
        self.assertTrue(self.overlay.child_in_alt)

    def test_notices_it_leaving(self):
        self.overlay.track_output(b"\x1b[?1049h")
        self.overlay.track_output(b"\x1b[?1049l")
        self.assertFalse(self.overlay.child_in_alt)

    def test_last_switch_in_one_chunk_wins(self):
        self.overlay.track_output(b"\x1b[?1049h stuff \x1b[?1049l more \x1b[?1049h")
        self.assertTrue(self.overlay.child_in_alt)

    def test_unrelated_output_changes_nothing(self):
        self.overlay.track_output(b"\x1b[?1049h")
        self.overlay.track_output(b"\x1b[31mjust some red text\x1b[0m")
        self.assertTrue(self.overlay.child_in_alt)


class ScreenHandoffTests(unittest.TestCase):
    def test_menu_takes_the_alternate_screen_from_a_plain_agent(self):
        overlay = Overlay(base_config(), b"\x1bg")
        drawn = overlay.enter()
        self.assertIn(b"\x1b[?1049h", drawn)
        self.assertTrue(overlay.open)

    def test_menu_does_not_switch_screens_under_an_alt_screen_agent(self):
        # codex already owns the alternate buffer; toggling it would drop the
        # agent's screen entirely.
        overlay = Overlay(base_config(), b"\x1bg")
        overlay.track_output(b"\x1b[?1049h")
        drawn = overlay.enter()
        self.assertNotIn(b"\x1b[?1049h", drawn)

        overlay.menu.done = True
        restored = overlay.leave()
        self.assertNotIn(b"\x1b[?1049l", restored)

    def test_agent_output_is_held_and_replayed_afterwards(self):
        overlay = Overlay(base_config(), b"\x1bg")
        overlay.enter()
        overlay.hold(b"agent said this ")
        overlay.hold(b"and then this")
        overlay.menu.done = True
        restored = overlay.leave()
        self.assertIn(b"agent said this and then this", restored)
        self.assertFalse(overlay.open)

    def test_leaving_restores_the_main_screen(self):
        overlay = Overlay(base_config(), b"\x1bg")
        overlay.enter()
        overlay.menu.done = True
        restored = overlay.leave()
        self.assertIn(b"\x1b[?1049l", restored)

    def test_held_output_does_not_leak_into_the_next_open(self):
        overlay = Overlay(base_config(), b"\x1bg")
        overlay.enter()
        overlay.hold(b"stale")
        overlay.menu.done = True
        overlay.leave()
        overlay.enter()
        overlay.menu.done = True
        self.assertNotIn(b"stale", overlay.leave())

    def test_edits_reach_the_live_config(self):
        config = base_config()
        config["auto_continue"] = True
        overlay = Overlay(config, b"\x1bg")
        overlay.enter()
        overlay.menu.config["auto_continue"] = False
        overlay.menu.done = True
        overlay.leave()
        # Same dict object the running controller holds.
        self.assertFalse(config["auto_continue"])


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.menu = Menu(base_config())

    def test_space_toggles_a_checkbox(self):
        before = self.menu.config["auto_continue"]
        self.menu.handle(b" ")
        self.assertEqual(self.menu.config["auto_continue"], not before)

    def test_arrows_move_the_cursor_past_headers(self):
        first = self.menu.cursor
        self.menu.handle(b"\x1b[B")
        self.assertNotEqual(self.menu.cursor, first)
        self.assertTrue(self.menu.rows[self.menu.cursor].selectable)

    def test_walking_the_whole_menu_never_lands_on_a_header(self):
        for _ in range(len(self.menu.rows) * 2):
            self.menu.handle(b"\x1b[B")
            self.assertTrue(self.menu.rows[self.menu.cursor].selectable)

    def test_right_arrow_bumps_a_number_by_its_step(self):
        self.menu.cursor = next(
            i for i, row in enumerate(self.menu.rows) if row.path == ("grace_seconds",)
        )
        before = self.menu.config["grace_seconds"]
        self.menu.handle(b"\x1b[C")
        self.assertEqual(self.menu.config["grace_seconds"], before + 15)

    def test_numbers_stay_inside_their_bounds(self):
        self.menu.cursor = next(
            i for i, row in enumerate(self.menu.rows) if row.path == ("grace_seconds",)
        )
        for _ in range(500):
            self.menu.handle(b"\x1b[D")
        self.assertEqual(self.menu.config["grace_seconds"], 0)

    def test_editing_a_text_field(self):
        self.menu.cursor = next(
            i
            for i, row in enumerate(self.menu.rows)
            if row.path == ("continue_message",)
        )
        self.menu.handle(b"\r")
        self.assertTrue(self.menu.editing)
        for _ in range(20):
            self.menu.handle(b"\x7f")  # backspace the default away
        self.menu.handle(b"segue\r")
        self.assertFalse(self.menu.editing)
        self.assertEqual(self.menu.config["continue_message"], "segue")

    def test_escape_cancels_an_edit(self):
        self.menu.cursor = next(
            i
            for i, row in enumerate(self.menu.rows)
            if row.path == ("continue_message",)
        )
        before = self.menu.config["continue_message"]
        self.menu.handle(b"\r")
        self.menu.handle(b"lixo")
        self.menu.handle(b"\x1b")
        self.assertEqual(self.menu.config["continue_message"], before)

    def test_editing_the_ping_times(self):
        self.menu.cursor = next(
            i for i, row in enumerate(self.menu.rows) if row.path == ("ping", "times")
        )
        self.menu.handle(b"\r")
        for _ in range(40):
            self.menu.handle(b"\x7f")
        self.menu.handle(b"6:00, 17:30\r")
        self.assertEqual(self.menu.config["ping"]["times"], ["06:00", "17:30"])

    def test_a_bad_time_is_refused_not_saved(self):
        self.menu.cursor = next(
            i for i, row in enumerate(self.menu.rows) if row.path == ("ping", "times")
        )
        before = list(self.menu.config["ping"]["times"])
        self.menu.handle(b"\r")
        for _ in range(40):
            self.menu.handle(b"\x7f")
        self.menu.handle(b"25:99\r")
        self.assertEqual(self.menu.config["ping"]["times"], before)
        self.assertIn("invalid time", self.menu.status)

    def _goto(self, path):
        self.menu.cursor = next(
            i for i, row in enumerate(self.menu.rows) if row.path == path
        )

    def test_garbage_typed_into_a_number_is_refused(self):
        # Otherwise a string lands in an int field and the session crashes
        # later, exactly when it has to type `continue`.
        self._goto(("grace_seconds",))
        self.menu.handle(b" ")  # abre o editor
        self.menu.handle(b"q\r")
        self.assertEqual(self.menu.config["grace_seconds"], 60)
        self.assertIn("must be a number", self.menu.status)

    def test_a_typed_number_is_accepted(self):
        self._goto(("grace_seconds",))
        self.menu.handle(b" ")
        for _ in range(10):
            self.menu.handle(b"\x7f")
        self.menu.handle(b"120\r")
        self.assertEqual(self.menu.config["grace_seconds"], 120)

    def test_a_typed_number_keeps_its_suffix(self):
        self._goto(("grace_seconds",))
        self.menu.handle(b" ")
        for _ in range(10):
            self.menu.handle(b"\x7f")
        self.menu.handle(b"90s\r")
        self.assertEqual(self.menu.config["grace_seconds"], 90)

    def test_a_typed_number_is_clamped(self):
        self._goto(("grace_seconds",))
        self.menu.handle(b" ")
        for _ in range(10):
            self.menu.handle(b"\x7f")
        self.menu.handle(b"999999\r")
        self.assertEqual(self.menu.config["grace_seconds"], 3600)

    def test_a_hand_edited_string_in_a_number_field_is_repaired(self):
        config = base_config()
        config["grace_seconds"] = "45"  # alguem editou o toml na mao
        menu = Menu(config)
        self.assertEqual(menu.config["grace_seconds"], 45)
        self.assertFalse(menu.dirty, "reparo nao deve contar como edicao pendente")

    def test_unrepairable_value_falls_back_to_the_default(self):
        config = base_config()
        config["grace_seconds"] = "sei la"
        menu = Menu(config)
        self.assertEqual(menu.config["grace_seconds"], configmod.DEFAULTS["grace_seconds"])

    def test_choice_cycles(self):
        self.menu.cursor = next(
            i for i, row in enumerate(self.menu.rows) if row.path == ("ping", "agent")
        )
        self.assertEqual(self.menu.config["ping"]["agent"], "claude")
        self.menu.handle(b" ")
        self.assertEqual(self.menu.config["ping"]["agent"], "codex")
        self.menu.handle(b" ")
        self.assertEqual(self.menu.config["ping"]["agent"], "claude")

    def test_q_quits(self):
        self.menu.handle(b"q")
        self.assertTrue(self.menu.done)

    def test_typing_q_into_a_text_field_does_not_quit(self):
        self.menu.cursor = next(
            i
            for i, row in enumerate(self.menu.rows)
            if row.path == ("continue_message",)
        )
        self.menu.handle(b"\r")
        self.menu.handle(b"q")
        self.assertFalse(self.menu.done)

    def test_dirty_flag_tracks_real_changes(self):
        self.assertFalse(self.menu.dirty)
        self.menu.handle(b" ")
        self.assertTrue(self.menu.dirty)
        self.menu.handle(b" ")
        self.assertFalse(self.menu.dirty)

    def test_render_mentions_every_setting(self):
        # A window tall enough for the whole menu; short ones scroll instead.
        self.menu.resize((40, 100))
        drawn = self.menu.render()
        for row in self.menu.rows:
            self.assertIn(row.label, drawn)

    def test_render_survives_every_row_being_selected(self):
        for index, row in enumerate(self.menu.rows):
            if row.selectable:
                self.menu.cursor = index
                self.assertIn(row.label, self.menu.render())


class BoxTests(unittest.TestCase):
    def setUp(self):
        self.menu = Menu(base_config(), size=(24, 80))

    def test_box_is_centered(self):
        drawn = self.menu.render()
        # Every line is placed with an absolute cursor move to the same column.
        columns = {int(m.group(1)) for m in re.finditer(r"\x1b\[\d+;(\d+)H", drawn)}
        self.assertEqual(len(columns), 1)
        left = columns.pop()
        width = 62
        self.assertEqual(left - 1, (80 - width) // 2)

    def test_box_is_drawn_with_double_rules(self):
        drawn = self.menu.render()
        for corner in "╔╗╚╝":
            self.assertIn(corner, drawn)

    def _line_widths(self, menu):
        drawn = menu.render()
        return [
            len(re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", line))
            for line in re.split(r"\x1b\[\d+;\d+H", drawn)[1:]
        ]

    def test_every_line_of_the_box_is_the_same_width(self):
        # One character short on the title row and the top-right corner lands a
        # column off, which looks like a broken box.
        self.assertEqual(len(set(self._line_widths(self.menu))), 1)

    def test_the_title_row_stays_aligned_when_the_unsaved_mark_appears(self):
        self.menu.handle(b" ")  # toggle something so `dirty` turns on
        self.assertTrue(self.menu.dirty)
        self.assertEqual(len(set(self._line_widths(self.menu))), 1)

    def test_alignment_holds_at_any_width(self):
        for cols in (40, 62, 80, 120, 200):
            menu = Menu(base_config(), size=(40, cols))
            self.assertEqual(len(set(self._line_widths(menu))), 1, f"cols={cols}")

    def test_the_title_spells_autoMODe_with_MOD_picked_out(self):
        drawn = self.menu.render()
        # Bold around MOD only, and ended without dropping the border color.
        self.assertIn(f" auto{BOLD}MOD{NOBOLD}e ", drawn)

    def test_no_line_is_wider_than_the_terminal(self):
        for cols in (40, 60, 80, 120, 200):
            menu = Menu(base_config(), size=(40, cols))
            drawn = menu.render()
            for line in re.split(r"\x1b\[\d+;\d+H", drawn)[1:]:
                visible = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", line)
                self.assertLessEqual(len(visible), cols, f"cols={cols}")

    def test_a_short_window_keeps_the_selected_row_visible(self):
        menu = Menu(base_config(), size=(12, 80))
        last = max(i for i, row in enumerate(menu.rows) if row.selectable)
        menu.cursor = last
        self.assertIn(menu.rows[last].label, menu.render())

    def test_a_narrow_window_still_draws_a_box(self):
        menu = Menu(base_config(), size=(24, 30))
        self.assertIn("╔", menu.render())

    def test_theme_colors_the_border(self):
        claude = Menu(base_config(), theme=for_agent("claude"), size=(24, 80)).render()
        codex = Menu(base_config(), theme=for_agent("codex"), size=(24, 80)).render()
        self.assertIn(CLAUDE.accent, claude)
        self.assertIn(CODEX.accent, codex)
        self.assertNotEqual(CLAUDE.accent, CODEX.accent)

    def test_agent_name_picks_the_theme(self):
        self.assertEqual(for_agent("claude").name, "claude")
        self.assertEqual(for_agent("codex").name, "codex")
        self.assertEqual(for_agent(None).name, "automode")
        self.assertEqual(for_agent("vim").name, "automode")


if __name__ == "__main__":
    unittest.main()
