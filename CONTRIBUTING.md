# Contributing to automode

Thanks for being here. Issues and pull requests are both welcome, and you do not need
permission to open either.

## Ways to help that do not need code

- **Tell us a limit message we do not recognise.** This is the most valuable report
  there is: the whole project rests on reading a sentence that Anthropic and OpenAI can
  change whenever they like. Run `automode doctor`, paste the output and the message
  you saw.
- **Tell us about a terminal where the menu misbehaves.** Which terminal, which
  version, what you saw. Terminals disagree about a lot.
- **Translate the interface.** See below — it is one file and no code.

## Getting set up

No dependencies, no virtualenv needed. Python 3.11 or newer, macOS or Linux.

```bash
git clone https://github.com/adrielmendes28/automode
cd automode
python3 -m unittest discover -s tests -t .   # the whole suite, ~60s
python3 -m automode doctor                   # detector against real messages
python3 -m automode -- bash                  # exercise the wrapper, no quota spent
```

`python3 -m automode` runs it straight from the clone, so you never have to install
anything to try a change.

## Running things without burning quota

Almost nothing here needs a real agent:

- `python3 -m automode -- bash` (or `vim`, or `top`) proves the wrapper passes the
  terminal through: colors, resize, exit codes.
- The scheduling tests use an injected clock, so "wait until 5am" takes milliseconds.
- `tests/test_pty_overlay.py` spawns a fake agent under a real PTY.

If you do want to watch auto continue fire, write a script that prints a limit message
with a reset time a minute out, and wrap it. That is how it was developed.

## The shape of the code

| file | what it owns |
|---|---|
| `pty_runner.py` | the PTY, raw mode, the select loop. Bytes in and out, nothing clever. |
| `detect.py` | turning a repainted, border-wrapped, ANSI-riddled screen back into a sentence |
| `dialogs.py` | the blocking menus the agents park on |
| `controller.py` | the decisions: when to arm, when to type, when to keep quiet |
| `menu.py` / `overlay.py` / `theme.py` | the mod menu and the screen juggling behind it |
| `ping.py` | the headless ping and its launchd agent |
| `i18n.py` | interface strings |

Some conventions worth knowing before you change things:

- **The clock is injectable.** `Controller(config, clock=...)` is what makes the
  scheduling testable in milliseconds instead of hours. Please do not reach for
  `datetime.now()` inside the controller.
- **`tests/test_pty_overlay.py` drives a real terminal.** Anything about the menu
  opening or closing belongs there. Mocks will not catch it — the bug where a stray
  `q` got written into a numeric field only ever showed up in that file.
- **automode never prints while an agent owns the terminal.** A stray line corrupts
  the TUI. Diagnostics go to the log (`~/.local/state/automode/automode.log`).
- **No dependencies, ever.** The standard library covers all of this, and a tool that
  wraps your shell should not drag a dependency tree in with it.

## Adding a limit message

1. Add the exact wording to `detect.SAMPLES`.
2. Add a test to `tests/test_detect.py` asserting the datetime it should produce.
3. If a new regex is needed, keep the two-step shape: a trigger phrase, then a time
   near it. One big regex will fire on any "resets 6pm" sitting elsewhere on screen.

`automode doctor` prints every sample with what it parsed, so a broken pattern is
visible immediately.

## Adding a blocking menu

Add a `Prompt` to `dialogs.PROMPTS` with a `pattern` whose first group captures the
option number, and a `context` that proves the menu is really on screen. Read the
number from the text — never hardcode it, or a reordered menu silently picks the wrong
thing. Add the wording to `dialogs.SAMPLES` and a test.

## Adding a language

Copy the `"en"` block in `automode/i18n.py`, translate the values, and add the code to
`LANGUAGES`. That is the whole job — a key you miss falls back to English rather than
crashing.

Logs are deliberately English-only. A bug report is easier to read in one language.

## Pull requests

- One thing per PR.
- Tests for behaviour you add or fix. If you found a bug, the test that catches it is
  the valuable half.
- Explain *why* in the commit message. This codebase is full of decisions that look
  arbitrary until you know what they are avoiding (why the hotkey must arrive in one
  read, why closing the menu fakes a resize). Write for the person who finds your line
  in six months.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).

CI runs the suite on Linux and macOS. It has to be green.

## Reporting a bug

Include:

- what you ran and what happened,
- `automode doctor` output,
- your terminal and OS,
- the relevant bit of `~/.local/state/automode/automode.log`.

The log is where automode explains itself, since it cannot use your screen.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
