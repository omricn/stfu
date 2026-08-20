# Scheduled off-hours, with a user-picked clock format

**Date:** 2026-08-20
**Status:** approved, not yet implemented

## Problem

S.TFU monitors continuously from launch until exit. The only way to stop it
reacting is the tray's "Pause 15 min", which is ad-hoc, short, and has to be
re-triggered by hand.

The app exists to stop someone waking a sleeping house. That concern has hours.
During the day nobody cares how loud the room gets, but the app still watches,
still escalates the strike ladder, and still takes over the screen. The
operator needs to be able to say *"don't do any of this between these two
times"* once, in Settings, and have it hold every day.

## Decisions locked before design

Four questions were settled up front; each shaped the design materially.

| Question | Decision | Why |
|---|---|---|
| Polarity | **Off hours** — a window during which detection is disabled | Matches the request literally, and fails safe: an unset or corrupt schedule means *always monitoring*, which is what `config._coerce` already promises |
| Depth | **Fully off** — gate before `detector.push()` | Nothing is detected, logged as a trigger, or reacted to inside the window |
| Granularity | **One window, every day** | Two fields, one Settings row. A weekday/weekend split is additive later and does not invalidate this schema |
| Clock format reach | **Everywhere times are displayed** | Schedule rows, report table, report chart axis. CSV export stays ISO 8601 |

The window's start and end **are** written to the event log, so the report can
label the gap instead of showing missing data. This supersedes an earlier
answer of "no boundary events".

## Non-goals

- Per-weekday or per-day windows
- More than one window per day
- A one-off "disable until a given time" — that is what "Pause 15 min" is for
- Converting `nightly_reset_hour` to the new time format (considered, deferred:
  an int to string config migration for cosmetic gain)
- Changing CSV export formatting

## Architecture

### Why a per-frame gate and not a timer

The obvious implementation is a `threading.Timer` at each boundary calling the
existing `engine.pause()` / `engine.resume()`, mirroring `PAUSE_MINUTES` in
`app.py`. It needs no engine change at all. It is rejected:

- **Sleep.** A gaming PC suspends. A timer set for 22:00 does not fire across
  suspend, leaving the app in the wrong state indefinitely.
- **Drift and DST.** A fixed `timedelta` lands an hour off twice a year.
- **State conflation.** `pause()` is idempotent, so a manual "Pause 15 min"
  inside the window would have its `_auto_resume` silently un-pause the
  *schedule*.
- **Log noise.** `resume()` writes `app_resumed`, which is not what a schedule
  boundary means.

`Engine.handle_frame(rms, mono, wall)` already receives real calendar time and
already has exactly one gate (`if self.paused: return`). Evaluating the window
statelessly from `wall` on every frame is immune to all four problems: sleep,
hibernate, DST and NTP corrections need no handling, because the answer is
recomputed from scratch roughly 50 times a second.

### New modules

Two small pure modules, following the house preference for narrow files
(`levels.py` is 36 lines and sits separately from `detector.py`).

```python
# stfu/clock.py
CLOCK_FORMATS = ("12h", "24h")

def parse_time(text: str) -> int | None
    """Lenient parse to minutes since midnight. None if unparseable."""

def format_time(minutes: int, clock: str) -> str
    """7:00 AM | 07:00"""

def format_dt(moment: datetime, clock: str, *, seconds: bool = False) -> str
    """1:04:22 PM | 13:04:22"""
```

```python
# stfu/schedule.py
def is_off(now: datetime, start_min: int, end_min: int) -> bool
    """Half-open [start, end). Wraps midnight when start > end."""
```

Both are added to `PURE_MODULES` in `tests/test_boundaries.py`, so their
freedom from audio, UI and Win32 imports is mechanically enforced alongside the
existing six.

**Parsing is deliberately lenient, display is canonical.** `parse_time` accepts
`1pm`, `1 PM`, `1:30pm`, `13:00`, `13.00`. Rejecting `1pm` from someone who
selected 12-hour display would be perverse. The value is then redisplayed in
the configured format.

**Window semantics.** Half-open `[start, end)` so `07:00-22:00` and
`22:00-07:00` tile the day with no overlap and no gap.

| `start` vs `end` | Meaning |
|---|---|
| `start < end` | off when `start <= t < end` |
| `start > end` | off when `t >= start` or `t < end` (wraps midnight) |
| `start == end` | rejected at coercion; see below |

The midnight-wrap reasoning mirrors `StrikeManager._night_of`, which already
solves the same problem for `nightly_reset_hour`.

### Config

```python
# Scheduled off-hours
schedule_enabled:  bool = False
schedule_off_from: str  = "07:00"
schedule_off_to:   str  = "22:00"
clock_format:      str  = "24h"
```

Times are **always stored canonically as 24-hour `"HH:MM"`**, whatever the
display setting. `config.json` is therefore never ambiguous, and changing the
clock format is a pure display change that does not rewrite stored values.

`clock_format` defaults to `"24h"` because that is exactly what the app renders
today; no existing user's report changes format unasked.

Three new `_coerce` rules, all resolving toward *monitoring*, per that
function's existing contract that a bad config must never silently disable
detection:

| Condition | Action |
|---|---|
| `schedule_off_from` or `schedule_off_to` unparseable | reset that field to its default **and** set `schedule_enabled = False` |
| `schedule_off_from == schedule_off_to` | set `schedule_enabled = False` |
| `clock_format` not in `CLOCK_FORMATS` | reset to `"24h"` |

The equal-times case is rejected rather than interpreted: it is ambiguous
between a zero-length window and a 24-hour one, and the 24-hour reading would
disable detection permanently.

### Engine

```python
if self.paused:                    # manual pause stays first and cheapest
    return
if self._update_schedule(wall):    # True == inside off-hours
    return
event = self.detector.push(rms, now=mono)
```

`_update_schedule(wall)`:

1. Resolve the window from config; return `False` immediately if
   `schedule_enabled` is false.
2. Compute `off = schedule.is_off(...)`.
3. If `off != self._schedule_off`, write the boundary event, and **on the
   falling edge** (off-hours ending) call `self.detector.reset()`.
4. Store and return `off`.

The falling-edge reset is the one piece of real bookkeeping. Without it, the
detector's rolling windows still hold samples from hours earlier, and adaptive
mode would compare live audio against a stale baseline. This is exactly why
`Engine.resume()` already resets, and its existing comment explains the
ordering constraint.

Config is read per frame, so changing the schedule in Settings takes effect
immediately, with no restart — consistent with the app's existing behaviour of
rescanning sound folders on every trigger.

`scheduled_off` is exposed as a read-only boolean property for the UI. It is
named distinctly from the event types so the two never read as the same thing.

### Event log

`"schedule_suspended"` and `"schedule_resumed"` are added to `EVENT_TYPES` in
`logstore.py`.

Boundary behaviour in the awkward cases:

- **App starts inside the window.** `_schedule_off` initialises to `False`, so
  the first frame produces a rising edge and logs `schedule_suspended`. Honest: it
  means "off from this moment".
- **Mic lost across a boundary.** No frames means no edge, so the event lands
  late — on the first frame after the mic returns. The existing `mic_lost`
  event already explains that gap, so the report stays readable.
- **App exits inside the window.** No closing `schedule_resumed` is written. The
  report treats an unterminated band as running to the end of the data,
  exactly as it already handles an unterminated session.
- **Schedule disabled mid-window.** Produces a `schedule_resumed` edge and a
  detector reset on the next frame. Correct.

### Report

`reportdata.py` gains:

```python
def off_windows(events: list[dict]) -> list[tuple[datetime, datetime | None]]
    """Pair schedule_suspended/schedule_resumed into spans. Tolerates
    unpaired events; a trailing suspend yields (start, None)."""
```

Pure and testable without matplotlib, matching the module's stated contract
that every function tolerates malformed records.

`reportui.py` draws each span as an `axes.axvspan` in a dim fill, so the gap
reads as *scheduled off* rather than as missing data. Both new event kinds also
flow into `table_rows`, consistent with that module's comment: "Every event,
including mic loss and pauses -- gaps in coverage matter."

### Clock format application

| Site | Change |
|---|---|
| Schedule Settings rows | display via `format_time`, parse via `parse_time` on save |
| Report detail table | `reportui.py` `strftime("%H:%M:%S")` becomes `format_dt(row.at, clock, seconds=True)` |
| Report chart x-axis | bare `autofmt_xdate()` becomes an explicit `DateFormatter`, `%I:%M %p` or `%H:%M` |
| CSV export | **unchanged**, stays ISO 8601 — machine-readable output, not display |

Knock-on: `ReportWindow(root, logstore)` needs the config to know the format,
so that signature and its call site in `app.py` change.

### Settings

One new section using only existing helpers — no new widget code:

- `_add_section("Schedule")`
- `_add_bool("schedule_enabled", "Disable during these hours")`
- `_add_entry("schedule_off_from", "From")`
- `_add_entry("schedule_off_to", "To")`
- `_add_choice("clock_format", "Clock format", CLOCK_FORMATS)`

Already PIN-gated, because all of Settings is.

### Tray

A new `STATE_SCHEDULED_OFF` in `tray.py`, amber — amber already means
*deliberately not listening* — with tooltip `S.TFU - off on schedule`.

This matters for the same reason the live meter shows cooldown seconds: the app
already refuses to let a working cooldown and a dead microphone look identical
from the outside. A scheduled-off app must not look like a crashed one.

`_update_meter` in `app.py` caches the last state and calls `set_state` only on
change, so this is not 50 calls a second. Setting tray state from the capture
thread is already established practice — `_mic_lost` does it.

The shared amber is a deliberate simplification: two states differing only by
tooltip. A fourth colour is a two-line change if it proves confusing in use.

## Test plan

Roughly 30 tests, all runnable without a microphone.

**`clock.py`** — lenient parsing of `1pm`, `1 PM`, `1:30pm`, `13:00`, `13.00`;
`None` for junk, empty, `25:00`, `12:60`; parse/format round-trip in both
formats; midnight and noon rendered correctly in 12-hour form (`12:00 AM`,
`12:00 PM`, not `0:00 AM`).

**`schedule.py`** — non-wrapping window; midnight-wrapping window; half-open
boundaries (start inclusive, end exclusive); a full sweep of the day for one
window asserting exactly the expected minutes are off.

**`config.py`** — each of the three coercion rules; a valid schedule surviving a
save/load round-trip; times persisting as 24h after being entered in 12-hour
form.

**`engine.py`** — no trigger inside the window even at full-scale RMS; normal
triggering outside it; `detector.reset()` called on the falling edge and not on
the rising one; boundary events written once per transition, not per frame;
`schedule_enabled=False` monitors always; manual pause and the schedule
independent of each other; disabling the schedule mid-window producing an
immediate `schedule_resumed`.

**`reportdata.py`** — `off_windows` pairing; a trailing unpaired `schedule_suspended`
yielding `(start, None)`; a stray `schedule_resumed` ignored; new kinds appearing in
`table_rows`; CSV rows still ISO 8601.

**`test_boundaries.py`** — `clock` and `schedule` added to `PURE_MODULES`.

## Accepted trade-offs

- Boundary events are logged from the frame loop, so a boundary crossed while
  the mic is missing is recorded late. The existing `mic_lost` event covers the
  gap.
- An overlay already open when the window starts is not dismissed. The gate
  covers new detections only; killing a live window mid-interaction is worse.
- The window is local wall-clock time, so on the two DST days it spans 23 or 25
  real hours. This is correct for "off until 10 PM".
- Two tray states share the amber colour.

## Files touched

| File | Change |
|---|---|
| `stfu/clock.py` | new |
| `stfu/schedule.py` | new |
| `stfu/config.py` | 4 fields, 3 coercion rules |
| `stfu/engine.py` | the gate, `_update_schedule`, `scheduled_off` property |
| `stfu/logstore.py` | 2 event types |
| `stfu/reportdata.py` | `off_windows`, new kinds in `table_rows` |
| `stfu/reportui.py` | `axvspan` bands, formatted table and axis, config param |
| `stfu/settingsui.py` | one section, four rows |
| `stfu/tray.py` | `STATE_SCHEDULED_OFF` |
| `stfu/app.py` | cached tray state, `ReportWindow` call site |
| `tests/` | roughly 30 tests across 5 files, plus `test_boundaries.py` |
| `docs/DESIGN.md` | the trade-offs above |
| `README.md` | Settings and report sections |
| `CHANGELOG.md` | unreleased entry |
