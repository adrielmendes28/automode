# automode

**A mod menu for Claude Code and Codex.** It keeps your session alive across usage
limits, and puts your limit windows where your workday actually is.

```
❯ claude
...
■ You've hit your session limit · resets 6:20pm (America/Sao_Paulo)

   What do you want to do?
   ❯ 1. Upgrade your plan
     2. Upgrade to Team plan
     3. Stop and wait for limit to reset

[18:21:04] automode: picked option 3, sent 'continue'
```

You keep the normal Claude Code / Codex interface — same colors, same shortcuts,
same everything. `ctrl+g` opens the mod menu on top of it.

Pure Python standard library. No dependencies.

---

## The two features

### 1. Auto continue

You hit the limit at 2pm. The message says it resets at 6:20pm. At 6:20pm you are
not at your desk, so the work just sits there until you remember to come back and
type `continue`.

automode reads the message, works out the reset time, waits, and types it for you.

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

## Getting started

```bash
git clone https://github.com/adrielmendes28/automode
cd automode
python3 -m automode install
```

That writes a launcher to `~/.local/bin/automode` and adds two aliases to your shell:

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

If you use pipx or uv, `pipx install .` works too and the launcher is skipped.

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

Issues and pull requests are welcome. The project has no dependencies and never
should — the standard library covers all of it.

```bash
python3 -m unittest discover -s tests -t .   # the whole suite
python3 -m automode doctor                   # detector against real messages
python3 -m automode -- bash                  # exercise the wrapper, no quota spent
```

Some notes for anyone touching the code:

- **The clock is injectable** (`Controller(config, clock=...)`), so the scheduling
  tests wait until 5am in milliseconds instead of hours. Please keep it that way.
- **`tests/test_pty_overlay.py` drives a real PTY** — it spawns automode, presses
  keys, and reads what a terminal would have received. Anything about the menu
  opening or closing belongs there; mocks will not catch it.
- **A new limit message** goes in `detect.SAMPLES`, a new blocking menu in
  `dialogs.PROMPTS`. Both are covered by `automode doctor` and by tests.
- **A new language** is a copy of the `"en"` block in `automode/i18n.py` with the
  values translated. Missing keys fall back to English rather than crashing.
- Logs are deliberately English-only — a bug report is easier to read in one language.

## License

MIT
