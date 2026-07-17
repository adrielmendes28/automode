"""The overlay menu: a centered box, drawn by hand with ANSI.

Not curses: automode already holds the terminal in raw mode and already reads
every keystroke, so curses would only fight it for control. The same renderer
serves both the in-session overlay and the standalone `automode menu`.

The look is deliberately Turbo Vision — a double-ruled box floating in the
middle of the screen, an inverted bar for the selected row — and it borrows
its color from whichever agent it is covering.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any

from . import config as configmod
from .i18n import LANGUAGES, set_language, t
from .theme import BOLD, DIM, RESET, Theme, for_agent
from .timeutil import local_tz_name, parse_hhmm

ESC = "\x1b"
ALT_SCREEN_ON = f"{ESC}[?1049h"
ALT_SCREEN_OFF = f"{ESC}[?1049l"
CURSOR_HIDE = f"{ESC}[?25l"
CURSOR_SHOW = f"{ESC}[?25h"
CLEAR = f"{ESC}[H{ESC}[2J"

TL, TR, BL, BR, H, V = "╔", "╗", "╚", "╝", "═", "║"
LT, RT = "╠", "╣"

LABEL_WIDTH = 21
BOX_WIDTH = 62
MIN_WIDTH = 34
MIN_HEIGHT = 8


@dataclass
class Row:
    kind: str
    label: str = ""
    path: tuple[str, ...] = ()
    options: list[str] = field(default_factory=list)
    step: int = 1
    lo: int = 0
    hi: int = 10_000
    suffix: str = ""
    hint: str = ""
    placeholder: str = "(vazio)"

    @property
    def selectable(self) -> bool:
        return self.kind != "header"


def build_rows() -> list[Row]:
    """The menu, in the current language. Rebuild it when the language changes."""
    return [
        Row("header", t("section.continue")),
        Row("bool", t("row.auto_continue"), ("auto_continue",),
            hint=t("hint.auto_continue")),
        Row("text", t("row.continue_message"), ("continue_message",),
            hint=t("hint.continue_message")),
        Row("int", t("row.grace_seconds"), ("grace_seconds",), step=15, lo=0, hi=3600,
            suffix="s", hint=t("hint.grace_seconds")),
        Row("int", t("row.idle_guard_seconds"), ("idle_guard_seconds",), step=1, lo=0,
            hi=120, suffix="s", hint=t("hint.idle_guard_seconds")),
        Row("bool", t("row.answer_limit_prompt"), ("answer_limit_prompt",),
            hint=t("hint.answer_limit_prompt")),
        Row("header", t("section.ping")),
        Row("bool", t("row.ping_enabled"), ("ping", "enabled"),
            hint=t("hint.ping_enabled")),
        Row("text", t("row.ping_message"), ("ping", "message")),
        Row("times", t("row.ping_times"), ("ping", "times"), hint=t("hint.ping_times")),
        Row("choice", t("row.ping_agent"), ("ping", "agent"),
            options=["claude", "codex"], hint=t("hint.ping_agent")),
        Row("int", t("row.catchup_minutes"), ("ping", "catchup_minutes"), step=5, lo=0,
            hi=240, suffix="min", hint=t("hint.catchup_minutes")),
        Row("int", t("row.ping_idle_seconds"), ("ping", "idle_seconds"), step=5, lo=0,
            hi=300, suffix="s", hint=t("hint.ping_idle_seconds")),
        Row("header", t("section.general")),
        Row("choice", t("row.language"), ("language",), options=list(LANGUAGES),
            hint=t("hint.language")),
        Row("bool", t("row.notify"), ("notify",)),
        Row("text", t("row.hotkey"), ("hotkey",), hint=t("hint.hotkey")),
        Row("text", t("row.timezone"), ("timezone",),
            placeholder=t("value.system_tz", zone=local_tz_name()),
            hint=t("hint.timezone")),
    ]


def _get(config: dict, path: tuple[str, ...]) -> Any:
    node: Any = config
    for key in path:
        node = node[key]
    return node


def _set(config: dict, path: tuple[str, ...], value: Any) -> None:
    node = config
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def terminal_size(fd: int = 1) -> tuple[int, int]:
    try:
        size = os.get_terminal_size(fd)
        return size.lines, size.columns
    except OSError:
        return 24, 80


class Menu:
    """Menu state machine. Feed it keys, ask it to render."""

    def __init__(
        self,
        config: dict[str, Any],
        theme: Theme | None = None,
        size: tuple[int, int] = (24, 80),
    ):
        self.config = copy.deepcopy(config)
        self.theme = theme or for_agent(None)
        set_language(str(self.config.get("language", "")))
        self.rows = build_rows()
        self._coerce()
        self.original = copy.deepcopy(self.config)
        self.cursor = next(i for i, row in enumerate(self.rows) if row.selectable)
        self.editing = False
        self.edit_buffer = ""
        self.status = ""
        self.done = False
        self.size = size
        self._top = 0  # first content line shown, when the window is short

    # ---- state -------------------------------------------------------

    @property
    def dirty(self) -> bool:
        return self.config != self.original

    def resize(self, size: tuple[int, int]) -> None:
        self.size = size

    def _move(self, delta: int) -> None:
        index = self.cursor
        for _ in range(len(self.rows)):
            index = (index + delta) % len(self.rows)
            if self.rows[index].selectable:
                self.cursor = index
                return

    def _value(self, row: Row) -> str:
        """The value as plain text — width math needs it free of escapes."""
        value = _get(self.config, row.path)
        if row.kind == "bool":
            return "[X]" if value else "[ ]"
        if row.kind == "int":
            return f"{value}{row.suffix}"
        if row.kind == "times":
            return ", ".join(value) if value else t("value.none")
        if row.kind == "choice":
            return "  ".join(
                f"({'o' if opt == value else ' '}) {self._option_label(row, opt)}"
                for opt in row.options
            )
        return str(value) if str(value) else row.placeholder

    def _option_label(self, row: Row, option: str) -> str:
        if row.path == ("language",):
            return LANGUAGES.get(option, option)
        return option

    def _edit_text(self, row: Row) -> str:
        value = _get(self.config, row.path)
        if row.kind == "times":
            return ", ".join(value)
        return str(value)

    def _coerce(self) -> None:
        """Repair values a hand-edited config file may have gotten wrong."""
        for row in self.rows:
            if not row.selectable:
                continue
            try:
                value = _get(self.config, row.path)
            except (KeyError, TypeError):
                continue
            if row.kind == "int" and not isinstance(value, int):
                try:
                    _set(self.config, row.path, int(str(value).strip()))
                except ValueError:
                    _set(self.config, row.path, configmod.default_for(row.path))
            elif row.kind == "times" and not isinstance(value, list):
                _set(self.config, row.path, configmod.default_for(row.path))

    def _commit_edit(self) -> None:
        row = self.rows[self.cursor]
        text = self.edit_buffer.strip()
        if row.kind == "int":
            # Never let a typo become a string in a numeric field: the session
            # would crash later, at the exact moment it had to type `continue`.
            digits = text[: -len(row.suffix)] if row.suffix and text.endswith(row.suffix) else text
            try:
                value = int(digits)
            except ValueError:
                self.status = t("menu.not_a_number", value=text)
                self.editing = False
                return
            _set(self.config, row.path, max(row.lo, min(row.hi, value)))
        elif row.kind == "times":
            entries = [part.strip() for part in text.split(",") if part.strip()]
            bad = [entry for entry in entries if parse_hhmm(entry) is None]
            if bad:
                self.status = t("menu.bad_time", value=", ".join(bad))
                self.editing = False
                return
            normalized = []
            for entry in entries:
                hour, minute = parse_hhmm(entry)
                normalized.append(f"{hour:02d}:{minute:02d}")
            _set(self.config, row.path, sorted(set(normalized)))
        else:
            _set(self.config, row.path, text)
        self.editing = False
        self.status = ""

    def _activate(self, row: Row) -> None:
        if row.kind == "bool":
            _set(self.config, row.path, not _get(self.config, row.path))
        elif row.kind == "choice":
            options = row.options
            current = _get(self.config, row.path)
            index = options.index(current) if current in options else -1
            _set(self.config, row.path, options[(index + 1) % len(options)])
            self._relabel(row)
        else:
            self.editing = True
            self.edit_buffer = self._edit_text(row)

    def _relabel(self, row: Row) -> None:
        """Redraw the menu in the new language, keeping the cursor put."""
        if row.path != ("language",):
            return
        set_language(str(_get(self.config, ("language",))))
        at = self.cursor
        self.rows = build_rows()
        self.cursor = min(at, len(self.rows) - 1)

    def _adjust(self, row: Row, delta: int) -> None:
        if row.kind == "int":
            value = int(_get(self.config, row.path)) + delta * row.step
            _set(self.config, row.path, max(row.lo, min(row.hi, value)))
        elif row.kind == "bool":
            _set(self.config, row.path, delta > 0)
        elif row.kind == "choice":
            options = row.options
            current = _get(self.config, row.path)
            index = options.index(current) if current in options else 0
            _set(self.config, row.path, options[(index + delta) % len(options)])
            self._relabel(row)

    def save(self) -> None:
        try:
            configmod.save(self.config)
            self.original = copy.deepcopy(self.config)
            self.status = t("menu.saved")
        except (OSError, TypeError) as exc:
            self.status = t("menu.save_failed", error=exc)

    # ---- input -------------------------------------------------------

    def handle(self, data: bytes) -> None:
        """Feed raw keyboard bytes."""
        text = data.decode("utf-8", errors="replace")
        index = 0
        while index < len(text):
            if text.startswith(f"{ESC}[", index) and index + 2 < len(text):
                self._handle_arrow(text[index + 2])
                index += 3
                continue
            char = text[index]
            index += 1
            self._handle_char(char)

    def _handle_arrow(self, code: str) -> None:
        if self.editing:
            return
        row = self.rows[self.cursor]
        if code == "A":
            self._move(-1)
        elif code == "B":
            self._move(1)
        elif code == "C":
            self._adjust(row, 1)
        elif code == "D":
            self._adjust(row, -1)

    def _handle_char(self, char: str) -> None:
        if self.editing:
            self._handle_edit_char(char)
            return
        if char in ("q", "\x03", "\x07", ESC):  # q, ctrl-c, ctrl-g, esc
            self.done = True
        elif char == "s":
            self.save()
        elif char in ("\r", "\n", " "):
            self._activate(self.rows[self.cursor])
        elif char == "k":
            self._move(-1)
        elif char == "j":
            self._move(1)

    def _handle_edit_char(self, char: str) -> None:
        if char in ("\r", "\n"):
            self._commit_edit()
        elif char == ESC:
            self.editing = False
            self.status = ""
        elif char in ("\x7f", "\x08"):
            self.edit_buffer = self.edit_buffer[:-1]
        elif char >= " ":
            self.edit_buffer += char

    # ---- rendering ---------------------------------------------------

    def _content(self, inner: int) -> list[tuple[str, bool]]:
        """Body lines as (plain text, is_selected)."""
        lines: list[tuple[str, bool]] = []
        for index, row in enumerate(self.rows):
            if row.kind == "header":
                if lines:
                    lines.append(("", False))
                lines.append((f" {row.label}", False))
                continue
            selected = index == self.cursor
            pointer = "▸" if selected else " "
            label = row.label.ljust(LABEL_WIDTH)
            lines.append((f" {pointer} {label} {self._value(row)}", selected))
        return lines

    def _footer(self) -> str:
        row = self.rows[self.cursor]
        if self.editing:
            return f" {row.label}: {self.edit_buffer}_"
        if self.status:
            return f" {self.status}"
        return f" {row.hint}" if row.hint else ""

    def render(self) -> str:
        rows, cols = self.size
        width = max(min(BOX_WIDTH, cols - 2), MIN_WIDTH)
        inner = width - 2

        body = self._content(inner)
        # Keep the cursor on screen when the window is too short for everything.
        # The box costs 5 lines of chrome; leave one more so it never hugs the edge.
        available = max(rows - 6, MIN_HEIGHT)
        if len(body) > available:
            selected_at = next(
                (i for i, (_, sel) in enumerate(body) if sel), self._top
            )
            if selected_at < self._top:
                self._top = selected_at
            elif selected_at >= self._top + available:
                self._top = selected_at - available + 1
            self._top = max(0, min(self._top, len(body) - available))
            body = body[self._top : self._top + available]
        else:
            self._top = 0

        height = len(body) + 5  # borders, title rule, footer rule, footer
        top = max((rows - height) // 2, 0)
        left = max((cols - width) // 2, 0)

        accent = self.theme.accent
        title = " automode "
        if self.dirty:
            title = " automode * "
        rule = H * (inner - len(title) - 3)

        out = [CLEAR, CURSOR_HIDE]
        line_no = top + 1

        def place(text: str) -> None:
            nonlocal line_no
            out.append(f"{ESC}[{line_no};{left + 1}H{text}")
            line_no += 1

        place(f"{accent}{TL}{H}{H}{self.theme.title}{title}{RESET}{accent}{rule}{TR}{RESET}")
        for text, selected in body:
            cell = text[:inner].ljust(inner)
            if selected:
                cell = f"{self.theme.select}{cell}{RESET}"
            elif text.strip() and not text.startswith("  "):
                cell = f"{accent}{BOLD}{cell}{RESET}"  # section header
            place(f"{accent}{V}{RESET}{cell}{accent}{V}{RESET}")

        place(f"{accent}{LT}{H * inner}{RT}{RESET}")
        footer = self._footer()[:inner].ljust(inner)
        place(f"{accent}{V}{RESET}{DIM}{footer}{RESET}{accent}{V}{RESET}")
        keys = t("menu.keys")
        place(f"{accent}{V}{RESET}{keys[:inner].ljust(inner)}{accent}{V}{RESET}")
        place(f"{accent}{BL}{H * inner}{BR}{RESET}")

        return "".join(out)


def run_standalone() -> int:
    """`automode menu` outside a session."""
    import sys
    import termios
    import tty

    fd = sys.stdin.fileno()
    if not sys.stdin.isatty():
        sys.stderr.write("automode: menu precisa de um terminal\n")
        return 1

    menu = Menu(configmod.load(), size=terminal_size())
    old = termios.tcgetattr(fd)
    out = sys.stdout
    try:
        tty.setraw(fd)
        out.write(ALT_SCREEN_ON)
        while not menu.done:
            menu.resize(terminal_size())
            out.write(menu.render())
            out.flush()
            data = os.read(fd, 1024)
            if not data:
                break
            menu.handle(data)
    finally:
        out.write(ALT_SCREEN_OFF + CURSOR_SHOW)
        out.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    if menu.dirty:
        print("automode: saiu sem salvar (use `s` pra salvar)")
    return 0
