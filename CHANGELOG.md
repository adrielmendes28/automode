# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-07-17

### Changed

- Published to PyPI as `automode-cli`. PyPI strips `-`, `_` and `.` before comparing
  names, so plain `automode` reads as identical to the existing `auto-mode` and is
  refused. The command, the import and the repo are all still `automode`.
- Internals split into three layers: `agents/` (what we know about Claude Code and
  Codex), `terminal/` (the PTY and the screen), `core/` (settings, state, time). No
  behaviour change.

### Documentation

- A FAQ answering what people search for when they are stuck: whether Claude Code can
  continue by itself after the limit resets, when the 5-hour window starts, and
  whether any of this gets around the limits (it does not).

## [0.1.0] - 2026-07-17

First release.

### Added

- **Auto continue.** Reads the usage-limit message off the agent's screen, works out
  when it resets, waits, and types `continue`. Recognises five wordings across Claude
  Code and Codex: absolute dates, wall-clock readings with and without a timezone,
  weekday resets, and relative durations.
- **Answering the blocking menu.** Hitting the limit parks the agent on a choice
  ("Upgrade your plan / … / Stop and wait for limit to reset"). automode picks the one
  that costs nothing, reading the option number out of the screen rather than assuming
  it, so a reordered menu still gets the right answer.
- **Auto ping.** Sends a prompt at times you choose, so the 5-hour window starts before
  your day does. Works inside an open session, or headless via `automode ping` with a
  launchd agent for when the terminal is closed and you are asleep.
- **The mod menu.** `ctrl+g` (or `alt+g`) floats a settings box over the running agent,
  tinted to match whichever one it is covering.
- **`automode install`.** One command for the launcher and the `claude`/`codex`
  aliases. Works without pipx or uv.
- **English and Portuguese**, switchable from the menu.
- **`automode doctor`**, which checks the detector against every known limit message
  and blocking menu. It is the first thing to run when an agent changes its wording.

### Notes

- macOS and Linux. The wrapper is POSIX PTY code; the scheduler currently only speaks
  launchd. On Linux, point cron or a systemd timer at `automode ping`.
- No dependencies, and there is no plan to add any.

[Unreleased]: https://github.com/adrielmendes28/automode/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/adrielmendes28/automode/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/adrielmendes28/automode/releases/tag/v0.1.0
