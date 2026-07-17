<p align="center">
  <img src="https://raw.githubusercontent.com/adrielmendes28/automode/main/docs/logo.svg" alt="automode" width="440">
</p>

<p align="center">
  <strong>A mod menu for Claude Code and Codex.</strong><br>
  It keeps your session alive across usage limits, and puts your limit windows
  where your workday actually is.
</p>

<p align="center">
  <a href="https://github.com/adrielmendes28/automode/actions/workflows/tests.yml"><img src="https://github.com/adrielmendes28/automode/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="https://github.com/adrielmendes28/automode/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/dependencies-none-brightgreen.svg" alt="no dependencies">
</p>

<p align="center">
  <a href="#getting-started">Getting started</a> ·
  <a href="#1-auto-continue">Auto continue</a> ·
  <a href="#2-auto-ping">Auto ping</a> ·
  <a href="https://github.com/adrielmendes28/automode/blob/main/CONTRIBUTING.md">Contributing</a>
</p>

---

You keep the normal Claude Code / Codex interface — same colors, same shortcuts, same
everything. `ctrl+g` opens the mod menu on top of it, wearing the color of whichever
agent it is covering.

<p align="center">
  <img src="https://raw.githubusercontent.com/adrielmendes28/automode/main/docs/menu-claude.png" alt="The automode menu over Claude Code" width="49%">
  <img src="https://raw.githubusercontent.com/adrielmendes28/automode/main/docs/menu-codex.png" alt="The automode menu over Codex" width="49%">
</p>

Pure Python standard library. No dependencies.

## The two features

### 1. Auto continue

You hit the limit at 2pm. The message says it resets at 6:20pm. At 6:20pm you are
not at your desk, so the work just sits there until you remember to come back and
type `continue`.

automode reads the message, works out the reset time, waits, and types it for you.

![Auto continue picking the session back up after the limit reset](https://raw.githubusercontent.com/adrielmendes28/automode/main/docs/auto-continue.png)

That is a real session: `oi` hits the session limit, automode sees it resets at 12am,
waits, types `continue` on its own, and Claude picks the work back up.

It also answers the menu the agent leaves on screen. That part matters more than it
sounds: hitting the limit does not just print a message, it parks the agent on a
blocking choice. Typing `continue` at that screen does nothing at all — the answer
has to come first. automode picks the option that costs nothing and waits for the
reset (`Stop and wait for limit to reset` on Claude, `Keep current model` on Codex),
reading the option number out of the screen rather than assuming it.

### 2. Auto ping

This is the one that changes your day.

**Your 5-hour window starts on your first prompt, not at a fixed hour.** So if your
first "hi" of the morning is at 8:00, your window ends at 13:00 — right in the
middle of the workday. You run out at lunch and wait.

Send that first prompt at **5:00** instead and the whole thing shifts:

| | first prompt | window resets | resets again |
|---|---|---|---|
| without automode | 08:00 | 13:00 🙃 | 18:00 |
| **with automode** | **05:00** | **10:00** ✅ | **15:00** ✅ |

You start at 8:00 with a fresh window, it renews at 10:00 while you are working, and
again at 15:00 — still inside office hours. Both renewals land while you are at the
keyboard instead of while you are asleep or gone for the day.

Nobody wakes up at 5am to type "hi". automode does it for you, on both Claude and
Codex, with the terminal closed and you asleep.

![Auto ping opening the usage window on its own](https://raw.githubusercontent.com/adrielmendes28/automode/main/docs/auto-ping.png)

Nobody typed that `oi` — the ping did, at the hour you picked. The window is open now,
and it will renew while you are at the keyboard instead of while you are asleep.

## Getting started

```bash
pipx install automode     # or: uv tool install automode
automode install
```

No pipx or uv? Run it straight from a clone — there is nothing to build:

```bash
git clone https://github.com/adrielmendes28/automode
cd automode
python3 -m automode install
```

Either way, `automode install` points your shell at it:

```sh
alias claude='automode claude'
alias codex='automode codex'
```

Open a new terminal, and that is it — `claude` now has the mods.

```
claude          the agent, with the mods
\claude         the agent, bare (the backslash skips the alias)
ctrl+g          the mod menu, from inside a session
automode menu   the same menu, from outside
```

Requires Python 3.11+ and macOS or Linux.

### Turn on the 5am ping

```bash
automode menu               # turn on auto ping, set your times
automode schedule install   # schedule it with launchd (macOS)
```

> **launchd does not wake your Mac.** If the machine is asleep at 5:00 the ping only
> fires once it wakes, which defeats the whole point. Schedule the wake as well —
> `automode schedule install` prints the exact command:
>
> ```bash
> sudo pmset repeat wakeorpoweron MTWRFSU 04:58:00
> ```
>
> Check it with `pmset -g sched`, undo it with `sudo pmset repeat cancel`.

## Commands

```
automode claude [args...]     run claude with the mods (args pass through)
automode codex  [args...]     same for codex
automode -- <cmd> [args...]   wrap any other command

automode install              install the aliases and launcher
automode menu                 open the settings menu
automode status               show settings and what is scheduled
automode doctor               check the detector against known limit messages
automode ping                 send the ping now, with no session open
automode schedule install     schedule the ping with launchd (macOS)
automode uninstall            remove the aliases and the launcher
```

## Settings

The menu writes `~/.config/automode/config.toml`, but it is a plain file:

```toml
language = "en"             # "en" or "pt" — also switchable from the menu
auto_continue = true
continue_message = "continue"
answer_limit_prompt = true  # answer the blocking menu the limit leaves on screen
grace_seconds = 60          # how long to wait past the reset time
idle_guard_seconds = 5      # never type while you are typing
timezone = ""               # empty = system timezone
notify = true
hotkey = "ctrl+g, alt+g"

[ping]
enabled = false
message = "hi"
times = ["05:00", "17:00"]
agent = "claude"            # which agent the scheduled ping wakes
catchup_minutes = 30        # if the machine slept through it, still count for X min
idle_seconds = 20           # only ping when the session is idle
```

## How it works

```
your keyboard ──> automode ──> PTY ──> claude (normal interface, untouched)
your terminal <── automode <── PTY <──┘
                     │
                     ├─> copy of the output ──> detector ──> auto continue
                     └─> clock ────────────────────────────> auto ping
```

The agent runs inside a real pseudo-terminal, so it never knows it is wrapped:
colors, mouse, resize and exit codes all pass through byte for byte. automode only
reads a copy of what comes out and, at the right moment, writes into the PTY as if
you had typed.

### Reading the message is harder than it looks

The sentence never arrives in one piece. The TUI repaints constantly and wraps the
message inside its borders:

```
╭────────────────────────────────╮
│ ■ You've hit your usage limit. │
│ ...try again at Jul 23rd,      │
│ 2026 1:16 AM.                  │
╰────────────────────────────────╯
```

So before any regex runs, the text goes through: ANSI stripping (holding back escape
sequences cut in half between two reads), borders replaced with spaces, and all
whitespace collapsed onto one line. Then matching happens in two steps — first a
trigger (`hit your usage limit`, `limit reached`), and only within the next 400
characters does it look for a time. One big regex would happily fire on any
"resets 6pm" sitting elsewhere on screen.

Why not match on the red color? Because stripping the color is exactly what makes
the sentence readable again, and the color depends on your terminal theme.

Recognised formats — run `automode doctor` to watch them all parse:

| message | becomes |
|---|---|
| `try again at Jul 23rd, 2026 1:16 AM` | that exact moment |
| `resets 6:20pm (America/Sao_Paulo)` | next 18:20 in that zone |
| `Your limit will reset at 4pm` | next 16:00 |
| `resets Tue 9am` | next Tuesday 09:00 |
| `try again in 4 hours 32 minutes` | now + 4h32 |

## Caveats

- **It types for you.** When the limit comes back, the agent goes back to work on its
  own and may run tools while you sleep. If that bothers you, set
  `auto_continue = false` and use auto ping only.
- **False positives are possible.** If the text of a limit message shows up on screen
  without being a real limit (you pasted it into the chat, say), automode may arm
  itself for nothing. Everything it arms goes to `~/.local/state/automode/automode.log`.
- **The message may change.** The detector depends on what Anthropic and OpenAI print
  today. If they change it, `automode doctor` says so and the regex in
  `automode/detect.py` needs a nudge.
- **The ping costs a little quota** — that is precisely its job.
- **macOS and Linux.** The wrapper uses a POSIX PTY; the scheduler currently only
  speaks launchd (macOS). On Linux, point cron or a systemd timer at `automode ping`.

## Contributing

Issues and pull requests are welcome — see **[CONTRIBUTING.md](https://github.com/adrielmendes28/automode/blob/main/CONTRIBUTING.md)**.

The most valuable thing you can report is **a limit message we do not recognise**. The
whole project rests on reading a sentence that Anthropic and OpenAI can change whenever
they like, so a paste of the exact wording is worth more than a patch.

```bash
python3 -m unittest discover -s tests -t .   # the whole suite, no dependencies
python3 -m automode doctor                   # detector against real messages
python3 -m automode -- bash                  # exercise the wrapper, no quota spent
```

By participating you agree to the [Code of Conduct](https://github.com/adrielmendes28/automode/blob/main/CODE_OF_CONDUCT.md).

## License

MIT — see [LICENSE](https://github.com/adrielmendes28/automode/blob/main/LICENSE).
