"""automode: keep claude/codex sessions going across usage limits."""

from pathlib import Path

__version__ = "0.1.1"

#: The clone this package lives in. Anchored to the package, not to any one
#: module's depth, so moving files between subpackages cannot quietly break it.
#: The launcher and the launchd agent both point here, and a wrong value would
#: only surface months later, at 5am, with nobody awake to see it.
REPO_ROOT = Path(__file__).resolve().parent.parent
