"""The hotkey overlay: the menu on top of a running agent.

Several hotkeys can be live at once (`ctrl+g, alt+g` by default), because which
one reaches us depends on the terminal: macOS Terminal.app sends Option+G as
"©" unless you turn on "Use Option as Meta key", so ctrl+g is the one that
always arrives.

Two problems have to be solved to put a menu over someone else's TUI:

1. Telling alt+g apart from a real Escape. A terminal sends alt+g as ESC then
   'g' with no gap, so both bytes land in one read(). A human pressing Esc and
   then typing g cannot beat that, because the bytes arrive in separate reads. So the
   hotkey only counts when it is the whole chunk.

2. Not losing the agent's screen. We switch to the alternate screen buffer,
   which the terminal restores byte-for-byte on exit, and hold everything the
   agent prints meanwhile in a buffer to replay afterwards. If the agent is
   itself using the alternate screen (codex does), we have to put it back
   there before replaying, so we track that from its output.
"""

from __future__ import annotations

import re

from ..core.i18n import t
from .menu import ALT_SCREEN_OFF, ALT_SCREEN_ON, CURSOR_HIDE, CURSOR_SHOW, Menu
from .theme import Theme, for_agent

# The agent switching the alternate screen on/off, seen in its own output.
ALT_ON_RE = re.compile(rb"\x1b\[\?(?:1049|47|1047)h")
ALT_OFF_RE = re.compile(rb"\x1b\[\?(?:1049|47|1047)l")

# Anything longer than this is a paste or a mouse report, not a hotkey.
MAX_HOTKEY_BYTES = 4


def parse_hotkey(spec: str) -> bytes | None:
    """Turn "alt+g" / "ctrl+g" into the bytes the terminal actually sends."""
    text = spec.strip().lower().replace(" ", "")
    if not text:
        return None
    if "+" not in text:
        return text.encode() if len(text) == 1 else None
    modifier, _, key = text.rpartition("+")
    if len(key) != 1 or not key.isalpha():
        return None
    if modifier in ("alt", "meta", "option", "opt"):
        # Note: on macOS this only ever arrives if the terminal is set to send
        # Option as Meta. Terminal.app sends "©" for Option+G out of the box,
        # which is why ctrl+g is the default.
        return b"\x1b" + key.encode()
    if modifier in ("ctrl", "control", "c"):
        return bytes([ord(key) - 96])
    return None


def parse_hotkeys(spec: str) -> list[bytes]:
    """Several accepted spellings, comma separated: "ctrl+g, alt+g"."""
    found = []
    for part in str(spec).split(","):
        parsed = parse_hotkey(part)
        if parsed is not None and parsed not in found:
            found.append(parsed)
    return found


def describe_hotkey(spec: str) -> str:
    """The configured hotkeys, spelled for a human: "ctrl+g or alt+g"."""
    parts = [p.strip().lower() for p in str(spec).split(",") if p.strip()]
    return t("hotkey.join").join(parts) if parts else "ctrl+g"


class Overlay:
    """Menu state plus the terminal bookkeeping to float it over the agent."""

    def __init__(
        self,
        config: dict,
        hotkeys: list[bytes] | bytes,
        theme: Theme | None = None,
        size: tuple[int, int] = (24, 80),
    ):
        self.config = config
        self.hotkeys = [hotkeys] if isinstance(hotkeys, bytes) else list(hotkeys)
        self.theme = theme or for_agent(None)
        self.size = size
        self.open = False
        self.menu: Menu | None = None
        self.held = bytearray()
        self.child_in_alt = False

    def track_output(self, data: bytes) -> None:
        """Follow whether the agent has the alternate screen up."""
        last_on = None
        last_off = None
        for match in ALT_ON_RE.finditer(data):
            last_on = match.start()
        for match in ALT_OFF_RE.finditer(data):
            last_off = match.start()
        if last_on is None and last_off is None:
            return
        if last_off is None or (last_on is not None and last_on > last_off):
            self.child_in_alt = True
        else:
            self.child_in_alt = False

    def matches_hotkey(self, data: bytes) -> bool:
        return (
            not self.open
            and len(data) <= MAX_HOTKEY_BYTES
            and data in self.hotkeys
        )

    def hold(self, data: bytes) -> None:
        """Stash agent output produced while the menu is up."""
        self.held.extend(data)

    def resize(self, size: tuple[int, int]) -> bytes:
        self.size = size
        if self.menu is None:
            return b""
        self.menu.resize(size)
        return self.menu.render().encode()

    def enter(self, size: tuple[int, int] | None = None) -> bytes:
        if size is not None:
            self.size = size
        self.open = True
        self.menu = Menu(self.config, theme=self.theme, size=self.size)
        self.held.clear()
        prefix = "" if self.child_in_alt else ALT_SCREEN_ON
        return (prefix + CURSOR_HIDE + self.menu.render()).encode()

    def handle(self, data: bytes) -> bytes:
        """Feed keys to the menu; returns what to draw."""
        assert self.menu is not None
        self.menu.handle(data)
        if self.menu.done:
            return b""
        return self.menu.render().encode()

    @property
    def done(self) -> bool:
        return self.menu is not None and self.menu.done

    def leave(self) -> bytes:
        """Close the menu and hand the screen back to the agent."""
        assert self.menu is not None
        self.config.clear()
        self.config.update(self.menu.config)
        self.open = False
        self.menu = None

        # The terminal restores the agent's screen for us on the way out of the
        # alternate buffer; if the agent lives there too, we never left it.
        restore = b"" if self.child_in_alt else ALT_SCREEN_OFF.encode()
        replay = bytes(self.held)
        self.held.clear()
        return restore + CURSOR_SHOW.encode() + replay


def build(
    config: dict, agent: str | None = None, size: tuple[int, int] = (24, 80)
) -> Overlay | None:
    """Overlay for this config, or None if no hotkey is usable."""
    hotkeys = parse_hotkeys(str(config.get("hotkey", "ctrl+g")))
    if not hotkeys:
        return None
    return Overlay(config, hotkeys, theme=for_agent(agent), size=size)
