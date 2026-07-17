"""Prompts the agents put on screen when you hit the limit.

Hitting the limit does not just print a message — it leaves the agent sitting
on a menu, waiting for an answer:

    What do you want to do?
    > 1. Upgrade your plan
      2. Upgrade to Team plan
      3. Stop and wait for limit to reset

Typing `continue` at that screen picks nothing and goes nowhere. The blocking
choice has to be answered first.

The option number is read out of the text rather than hardcoded, so a
reordered menu still gets the right answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    """A blocking choice, and which option gets us back to work."""

    name: str
    #: group(1) must capture the number of the option we want.
    pattern: re.Pattern
    #: What the screen must also contain, to be sure this is really the prompt.
    context: re.Pattern
    confirm: bool = True


PROMPTS = (
    # claude: waiting is the whole point — the other options cost money.
    Prompt(
        name="claude-wait-for-reset",
        pattern=re.compile(
            r"(\d)\s*\.\s*Stop and wait for (?:the )?limit to reset", re.I
        ),
        context=re.compile(r"What do you want to do\?", re.I),
    ),
    # codex: keep the model we are on. The "(never show again)" variant is a
    # different option and must not be mistaken for this one.
    Prompt(
        name="codex-keep-model",
        pattern=re.compile(r"(\d)\s*\.\s*Keep current model(?!\s*\(never)", re.I),
        context=re.compile(r"Approaching rate limits|Switch to \S+ for lower", re.I),
    ),
)


@dataclass(frozen=True)
class Answer:
    prompt: Prompt
    key: str

    @property
    def name(self) -> str:
        return self.prompt.name


def find(text: str) -> Answer | None:
    """The blocking prompt on screen, and the key that dismisses it."""
    for prompt in PROMPTS:
        if not prompt.context.search(text):
            continue
        match = prompt.pattern.search(text)
        if match:
            return Answer(prompt, match.group(1))
    return None


SAMPLES = [
    (
        "claude-wait-for-reset",
        "3",
        "What do you want to do? "
        "❯ 1. Upgrade your plan "
        "2. Upgrade to Team plan "
        "3. Stop and wait for limit to reset",
    ),
    (
        "codex-keep-model",
        "2",
        "Approaching rate limits Switch to gpt-5.4-mini for lower credit usage? "
        "1. Switch to gpt-5.4-mini Small, fast, and cost-efficient model for "
        "simpler coding tasks. › 2. Keep current model "
        "3. Keep current model (never show again) Hide future rate limit "
        "reminders about switching models. Press enter to confirm or esc to go back",
    ),
]
