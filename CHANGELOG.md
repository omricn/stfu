# Changelog

All notable changes to S.TFU are documented here. The 1.0.0 entry is a
summary of what the app does rather than a diff, since it was the first public
release; everything after it is a real changelog.

## [1.1.0] — 2026-08-20

### Added

- A daily **scheduled off-hours window**, set in Settings: detection is switched
  off entirely between two times, every day, rather than merely muted. Nothing
  is detected, logged as a trigger, or reacted to while it's in force
- The window wraps midnight, so a range like 22:00–07:00 covers overnight
  without the operator having to think about the date boundary
- Off-hours boundaries are written to the event log, so the report can shade
  the span instead of leaving a gap that reads exactly like a dropped
  microphone
- A **clock format** preference (12-hour or 24-hour), used everywhere a time
  of day is shown — the schedule fields, the report's detail table, and the
  chart axis. Times are still stored canonically in 24-hour form, so changing
  the preference redisplays existing settings rather than rewriting them
- Off-hours times accept whatever's typed — `1pm`, `13:00`, `1:30 PM` — the
  same leniency in the box regardless of which display format is selected
- A tray state and matching live-meter message for scheduled off-hours, so
  the amber icon and the flat meter say *why* nothing is happening instead of
  looking like a dead microphone or a paused app

### Fixed

- **The report window could crash outright** on any log that had ever recorded
  a dropped microphone or a Pause 15 min. The log has always mixed naive and
  timezone-aware timestamps between different event types, and sorting a list
  containing both raised `TypeError: can't compare offset-naive and
  offset-aware datetimes`. Every timestamp is now normalised to naive local
  time before anything compares or sorts them
- **A Settings change could silently fail to reach the running app.** Saving
  wrote the coerced, validated values back onto the same `Config` object the
  engine already holds, rather than rebinding Settings' own reference to a
  fresh reload and leaving the engine with whatever was typed. Previously, an
  out-of-range value like `cooldown_seconds` would show clamped in Settings
  and on disk while the engine kept using the bad number until the app was
  restarted

### Removed

- The stubbed USB indicator light action, along with its `TODO` call sites and
  its mention in the design doc. It was registered and wired into the strike
  ladder but never talked to hardware, and no hardware was ever chosen for it
  — it read as unfinished work rather than a deliberate extension point

## [1.0.0] — 2026-08-19

### Detection

- Microphone-based yell detection, tuned for short spikes rather than
  sustained volume
- Three threshold modes: **Wizard** (the fixed number first-run calibration
  measured), **Manual** (set against a live meter), and **Adaptive** (tracks
  the room's baseline and ratchets downward only, never up)
- Optional sustain detection alongside the spike rule, with its own window
  and threshold
- Configurable detection window lengths and a cooldown after every trigger,
  so one long yell can't chain into several reactions
- Session-cumulative escalation with three reset modes (per-session, rolling,
  nightly) and a configurable cutover hour
- Pinned capture device (by name and host API), so the app never silently
  switches microphones
- Automatic recovery when the pinned microphone is unplugged and replugged

### Reactions

- First yell of a session: `Win+D` to the desktop, a random sound effect,
  and a near-fullscreen overlay whose close button jumps to a new spot after
  each of four clicks (both counts configurable)
- Every later yell that session: `Win+D`, a different sound, and a
  fullscreen message for a configurable number of seconds
- Optional pictures shown under the message in both popups, drawn from a
  user-supplied folder, never repeating the same one twice in a row
- Separate sound folders for the first yell and every later one, rescanned
  on every trigger so dropped-in clips work without a restart
- "Show popups" and "Play sounds" can each be switched off independently,
  including a log-only mode with both off
- A tray-only "Pause 15 min" control

### Setup

- A first-run wizard: welcome, microphone selection, three-sample
  calibration (quiet / speech / yell), a test step, PIN, sound bites, and
  autostart — asked once, never again
- Calibration places the threshold between measured speech and a measured
  yell, biased toward the yell so ordinary conversation doesn't trigger it
- A PIN gate on Settings, Recalibrate, Pause, and Exit — a speed bump, not a
  lock, and documented as such
- Autostart with Windows, reconciled with the saved setting on every launch
- A "Start over" control in Settings that wipes the pinned device, PIN,
  thresholds, and event log and relaunches into first-run setup, without
  touching sound clips or pictures
- Bundled starter sound effects, seeded into the user's data folder once at
  setup and never overwritten

### Reporting

- An append-only, crash-safe JSONL event log
- A report window: a chart of triggers over a session, a detail table, and
  a CSV export
- A live meter showing the current level, the threshold in force, and the
  seconds left on cooldown, so a working cooldown and a dead microphone
  don't look identical from the outside

### Privacy

- No audio is ever recorded, transmitted, or stored — each frame's loudness
  is computed and the samples are discarded immediately
- No network code anywhere in the project; nothing leaves the machine
- The only things written to disk are settings, a PIN hash (not the PIN
  itself), and event records (a timestamp, a level, and which action fired)

### Known limitations

- **Unsigned binary** — Windows SmartScreen will warn on the downloaded exe.
  `Unblock-File` clears it, or build from source.
- **Windows only** — the registry-based autostart, Win32 minimise/show-desktop
  calls, and WASAPI capture are all Windows-specific.
- **Exclusive-fullscreen games** — handled by dropping to the desktop first,
  but behaviour still varies by title; worth testing with the games you
  actually play.
