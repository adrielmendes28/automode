"""Colors for the overlay, picked from the agent it is floating over.

256-color rather than truecolor on purpose: macOS Terminal.app still does not
do 24-bit, and this has to look right in whatever terminal you already use.
"""

from __future__ import annotations

from dataclasses import dataclass

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
#: Ends bold without dropping the color, unlike RESET.
NOBOLD = "\x1b[22m"
DIM = "\x1b[2m"


@dataclass(frozen=True)
class Theme:
    name: str
    accent: str  # border and title
    select: str  # the highlighted row bar

    @property
    def title(self) -> str:
        return f"{self.accent}{BOLD}"


# 173 is the closest 256-color step to Claude's terracotta (#d7875f).
CLAUDE = Theme(name="claude", accent="\x1b[38;5;173m", select="\x1b[48;5;173m\x1b[30m")
# Codex gets the blue.
CODEX = Theme(name="codex", accent="\x1b[38;5;39m", select="\x1b[48;5;39m\x1b[30m")
PLAIN = Theme(name="automode", accent="\x1b[38;5;245m", select="\x1b[7m")

THEMES = {"claude": CLAUDE, "codex": CODEX}


def for_agent(agent: str | None) -> Theme:
    return THEMES.get((agent or "").lower(), PLAIN)
