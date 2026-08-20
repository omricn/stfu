# Scheduled Off-Hours Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a daily, Settings-configurable window during which S.TFU's detection is fully disabled, plus a 12h/24h clock format preference applied everywhere times are displayed.

**Architecture:** Two new pure-logic modules (`clock.py` for parsing/formatting wall-clock times, `schedule.py` for the window predicate) feed a single new gate in `Engine.handle_frame`, which already receives real calendar time. The window is recomputed from `wall` on every frame rather than driven by a timer, so sleep, hibernate, DST and NTP corrections need no handling at all. Window boundaries are written to the event log so the report can label the gap instead of showing missing data.

**Tech Stack:** Python 3.12, Tk/ttk, matplotlib, pytest. Windows-only app; all tests run headless without a microphone.

**Spec:** [2026-08-20-scheduled-off-hours-design.md](../specs/2026-08-20-scheduled-off-hours-design.md)

**Branch:** `feature/scheduled-off-hours` (already checked out, clean)

---

## Orientation for someone new to this codebase

Read these before starting. They explain constraints that will otherwise look arbitrary:

- **`tests/test_boundaries.py`** — six modules (`levels`, `config`, `detector`, `strikes`, `logstore`, `engine`) are mechanically forbidden from importing `sounddevice`, `tkinter`, `ctypes`, `pystray`, `matplotlib`, or `miniaudio`. The test walks their ASTs. Both new modules join that list, so **do not import Tk or audio into `clock.py` or `schedule.py`.**
- **`stfu/config.py:82`** — `_coerce`'s contract: *"Replace nonsensical values with defaults. A bad config must never silently disable detection."* Every new validation rule in Task 4 resolves toward monitoring. This is the safety-critical part of the feature.
- **`stfu/engine.py:3-8`** — two clocks are threaded through deliberately. `mono` is monotonic, for durations. `wall` is real calendar time, for anything a human reads. **The schedule uses `wall`.** Using `mono` would be a bug.
- **`stfu/engine.py:119`** — `resume()` calls `detector.reset()` and explains why. The schedule's falling edge needs the same treatment for the same reason.
- **`stfu/settingsui.py:300`** — `_save()` writes every field, round-trips through `save_config`/`load_config` so `_coerce` validates it, then re-displays the coerced result. Task 9 depends on this: coercion normalises `1pm` to `13:00`, and the re-display renders it back in the chosen format.

Run the suite with `./.venv/Scripts/python.exe -m pytest`. Baseline before starting: **484 passed, 24 skipped.**

---

## File structure

| File | Responsibility | Status |
|---|---|---|
| `stfu/clock.py` | Parse and format wall-clock times. Knows nothing about schedules. | Create |
| `stfu/schedule.py` | One predicate: is this moment inside the window? | Create |
| `stfu/config.py` | 4 new fields, 3 new coercion rules | Modify |
| `stfu/logstore.py` | 2 new event types | Modify |
| `stfu/engine.py` | The gate, edge detection, `scheduled_off` property | Modify |
| `stfu/reportdata.py` | `off_windows()` — pair boundary events into spans | Modify |
| `stfu/reportui.py` | Shaded bands, formatted table and axis | Modify |
| `stfu/settingsui.py` | Schedule section, format-aware time entries | Modify |
| `stfu/tray.py` | `STATE_SCHEDULED_OFF` | Modify |
| `stfu/meter.py` + `stfu/meterui.py` | Show scheduled-off in the live meter | Modify |
| `stfu/app.py` | Cached tray state, wiring | Modify |

`clock.py` and `schedule.py` are separate because formatting a time and deciding whether a moment is in a window are different jobs. This matches the house style — `levels.py` is 36 lines and sits separately from `detector.py`.

**Dependency order:** Tasks 1–5 are independent of each other after Task 1. Task 6 needs 1, 2, 4, 5. Tasks 7–11 need 4–6. Task 12 needs 10 and 11. Task 13 is last.

---

### Task 1: `clock.py` — parsing and formatting

**Files:**
- Create: `stfu/clock.py`
- Test: `tests/test_clock.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_clock.py`:

```python
from datetime import datetime

import pytest

from stfu.clock import CLOCK_FORMATS, format_dt, format_time, parse_time, to_canonical


@pytest.mark.parametrize(
    "text,expected",
    [
        ("7", 420),
        ("7:30", 450),
        ("07:30", 450),
        ("07.30", 450),
        ("13:00", 780),
        ("1pm", 780),
        ("1 PM", 780),
        ("1:30pm", 810),
        ("1:30 p.m.", 810),
        ("12am", 0),
        ("12:00 AM", 0),
        ("12pm", 720),
        ("  7:05  ", 425),
        ("23:59", 1439),
    ],
)
def test_parse_time_accepts_every_spelling_a_user_might_type(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "   ", "abc", "25:00", "12:60", "13pm", "0pm", "7:5", "-1:00", "1:00:00"],
)
def test_parse_time_rejects_what_is_not_a_time(text):
    assert parse_time(text) is None


def test_parse_time_rejects_non_strings():
    assert parse_time(None) is None
    assert parse_time(700) is None


def test_to_canonical_normalises_to_stored_form():
    assert to_canonical("1pm") == "13:00"
    assert to_canonical("7") == "07:00"
    assert to_canonical("12am") == "00:00"
    assert to_canonical("nonsense") is None


def test_format_time_renders_both_formats():
    assert format_time(420, "24h") == "07:00"
    assert format_time(420, "12h") == "7:00 AM"
    assert format_time(1320, "24h") == "22:00"
    assert format_time(1320, "12h") == "10:00 PM"


def test_format_time_gets_midnight_and_noon_right():
    # The classic 12-hour bug: hour 0 must read 12 AM, not 0 AM.
    assert format_time(0, "12h") == "12:00 AM"
    assert format_time(720, "12h") == "12:00 PM"
    assert format_time(0, "24h") == "00:00"


def test_every_minute_of_the_day_survives_a_round_trip():
    # The strongest guarantee available here: whatever we display, we can
    # read back. A display format that cannot be re-parsed would silently
    # reset the user's schedule the next time they saved Settings.
    for clock in CLOCK_FORMATS:
        for minutes in range(0, 24 * 60):
            rendered = format_time(minutes, clock)
            assert parse_time(rendered) == minutes, f"{clock} {minutes} -> {rendered}"


def test_format_dt_renders_time_of_day():
    moment = datetime(2026, 8, 20, 13, 4, 22)
    assert format_dt(moment, "24h") == "13:04"
    assert format_dt(moment, "24h", seconds=True) == "13:04:22"
    assert format_dt(moment, "12h") == "1:04 PM"
    assert format_dt(moment, "12h", seconds=True) == "1:04:22 PM"


def test_format_dt_does_not_strip_the_ten_from_ten_oclock():
    # Stripping the zero pad must not eat a significant digit.
    moment = datetime(2026, 8, 20, 10, 4, 0)
    assert format_dt(moment, "12h") == "10:04 AM"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_clock.py -q`
Expected: FAIL, collection error — `ModuleNotFoundError: No module named 'stfu.clock'`

- [ ] **Step 3: Write the implementation**

Create `stfu/clock.py`:

```python
"""Parsing and formatting wall-clock times for display.

Times are *stored* canonically as 24-hour "HH:MM" and *displayed* in whichever
format the operator picked, so a stored value never depends on a display
preference and switching format rewrites nothing.

Parsing is deliberately lenient. Someone who has selected 12-hour display and
types "1pm" means 13:00, and refusing that would be perverse -- so every
spelling this module can understand is accepted regardless of the current
setting, and only the redisplay is canonical.
"""

from __future__ import annotations

import re
from datetime import datetime

CLOCK_FORMATS = ("12h", "24h")

MINUTES_PER_DAY = 24 * 60

# hour, optional :mm or .mm, optional am/pm with optional dots.
_TIME = re.compile(
    r"^\s*(\d{1,2})\s*(?:[:.](\d{2}))?\s*([ap]\.?m\.?)?\s*$",
    re.IGNORECASE,
)


def parse_time(text: str) -> int | None:
    """Minutes since midnight, or None if `text` is not a time.

    Accepts "7", "7:30", "07.30", "13:00", "1pm", "1 PM", "1:30 p.m.".
    """
    if not isinstance(text, str):
        return None
    match = _TIME.match(text)
    if match is None:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    suffix = (match.group(3) or "").replace(".", "").lower()

    if minute > 59:
        return None
    if suffix:
        # A 12-hour clock has no hour 0 and no hour 13.
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12
        if suffix == "pm":
            hour += 12
    elif hour > 23:
        return None

    return hour * 60 + minute


def to_canonical(text: str) -> str | None:
    """Normalise any accepted spelling to the stored "HH:MM" form."""
    minutes = parse_time(text)
    if minutes is None:
        return None
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def format_time(minutes: int, clock: str) -> str:
    """Render minutes-since-midnight for display."""
    hour, minute = divmod(minutes % MINUTES_PER_DAY, 60)
    if clock == "12h":
        suffix = "AM" if hour < 12 else "PM"
        return f"{hour % 12 or 12}:{minute:02d} {suffix}"
    return f"{hour:02d}:{minute:02d}"


def format_dt(moment: datetime, clock: str, *, seconds: bool = False) -> str:
    """Render a datetime's time of day for display."""
    if clock == "12h":
        pattern = "%I:%M:%S %p" if seconds else "%I:%M %p"
        # %I is zero-padded and Windows has no %-I; strip the pad by hand.
        rendered = moment.strftime(pattern)
        return rendered[1:] if rendered.startswith("0") else rendered
    return moment.strftime("%H:%M:%S" if seconds else "%H:%M")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_clock.py -q`
Expected: PASS, 30 passed (the parametrised cases count individually)

- [ ] **Step 5: Commit**

```bash
git add stfu/clock.py tests/test_clock.py
git commit -m "feat: add clock.py, lenient time parsing with canonical display"
```

---

### Task 2: `schedule.py` — the window predicate

**Files:**
- Create: `stfu/schedule.py`
- Test: `tests/test_schedule.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_schedule.py`:

```python
from datetime import datetime

from stfu.schedule import is_off


def at(hour, minute=0):
    return datetime(2026, 8, 20, hour, minute)


DAY = 7 * 60      # 07:00
NIGHT = 22 * 60   # 22:00


def test_a_window_inside_one_day():
    # off from 07:00 to 22:00
    assert is_off(at(6, 59), DAY, NIGHT) is False
    assert is_off(at(7, 0), DAY, NIGHT) is True
    assert is_off(at(12, 0), DAY, NIGHT) is True
    assert is_off(at(21, 59), DAY, NIGHT) is True
    assert is_off(at(22, 0), DAY, NIGHT) is False
    assert is_off(at(23, 30), DAY, NIGHT) is False


def test_a_window_that_wraps_midnight():
    # off from 22:00 to 07:00
    assert is_off(at(21, 59), NIGHT, DAY) is False
    assert is_off(at(22, 0), NIGHT, DAY) is True
    assert is_off(at(23, 59), NIGHT, DAY) is True
    assert is_off(at(0, 0), NIGHT, DAY) is True
    assert is_off(at(6, 59), NIGHT, DAY) is True
    assert is_off(at(7, 0), NIGHT, DAY) is False
    assert is_off(at(12, 0), NIGHT, DAY) is False


def test_the_window_is_half_open_so_the_two_halves_tile_the_day():
    # Every minute is off in exactly one of the two complementary windows.
    for minutes in range(0, 24 * 60):
        moment = at(minutes // 60, minutes % 60)
        inside = is_off(moment, DAY, NIGHT)
        outside = is_off(moment, NIGHT, DAY)
        assert inside != outside, f"{moment} is in both or neither"


def test_a_non_wrapping_window_covers_exactly_its_own_minutes():
    off = sum(
        1 for m in range(0, 24 * 60) if is_off(at(m // 60, m % 60), DAY, NIGHT)
    )
    assert off == NIGHT - DAY == 900


def test_equal_start_and_end_is_never_off():
    # Ambiguous between zero-length and 24 hours. config._coerce rejects it
    # before it reaches here; this is the defensive second answer, and it is
    # the safe one -- 24 hours off would disable detection permanently.
    for hour in (0, 7, 23):
        assert is_off(at(hour), hour * 60, hour * 60) is False


def test_seconds_within_the_boundary_minute_do_not_matter():
    assert is_off(datetime(2026, 8, 20, 22, 0, 59), NIGHT, DAY) is True
    assert is_off(datetime(2026, 8, 20, 6, 59, 59), NIGHT, DAY) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_schedule.py -q`
Expected: FAIL, collection error — `ModuleNotFoundError: No module named 'stfu.schedule'`

- [ ] **Step 3: Write the implementation**

Create `stfu/schedule.py`:

```python
"""Does a moment fall inside the scheduled off-hours window?

Pure arithmetic on minutes since midnight. The window is half-open --
[start, end) -- so 07:00-22:00 and 22:00-07:00 tile the day with no overlap and
no gap, and a window whose start is later than its end simply wraps midnight.
StrikeManager._night_of solves the same wrap for the nightly reset cutover.
"""

from __future__ import annotations

from datetime import datetime


def is_off(now: datetime, start_min: int, end_min: int) -> bool:
    """True when `now` falls inside the off-hours window.

    `start_min` and `end_min` are minutes since midnight. Equal values are
    never off: the reading is ambiguous between a zero-length window and a
    whole day, and the whole-day reading would disable detection forever.
    """
    if start_min == end_min:
        return False
    minutes = now.hour * 60 + now.minute
    if start_min < end_min:
        return start_min <= minutes < end_min
    return minutes >= start_min or minutes < end_min
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_schedule.py -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add stfu/schedule.py tests/test_schedule.py
git commit -m "feat: add schedule.py, a half-open window that wraps midnight"
```

---

### Task 3: Enforce purity on the two new modules

**Files:**
- Modify: `tests/test_boundaries.py:6`

- [ ] **Step 1: Add both modules to the enforced list**

Change line 6 from:

```python
PURE_MODULES = ["levels", "config", "detector", "strikes", "logstore", "engine"]
```

to:

```python
PURE_MODULES = [
    "levels",
    "config",
    "detector",
    "strikes",
    "logstore",
    "engine",
    "clock",
    "schedule",
]
```

- [ ] **Step 2: Run the test to verify both new modules pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_boundaries.py -v`
Expected: PASS, 8 passed — including `test_pure_modules_have_no_io_dependencies[clock]` and `[schedule]`

- [ ] **Step 3: Commit**

```bash
git add tests/test_boundaries.py
git commit -m "test: hold clock and schedule to the same layering rule"
```

---

### Task 4: Config fields and coercion

**Files:**
- Modify: `stfu/config.py` — imports, `Config` dataclass, `_coerce`
- Test: `tests/test_config.py`

This is the safety-critical task. Every rule resolves toward *monitoring*.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_schedule_defaults_are_off():
    cfg = Config()
    assert cfg.schedule_enabled is False
    assert cfg.schedule_off_from == "07:00"
    assert cfg.schedule_off_to == "22:00"
    assert cfg.clock_format == "24h"


def test_a_valid_schedule_round_trips(tmp_path):
    path = tmp_path / "config.json"
    save_config(
        Config(
            schedule_enabled=True,
            schedule_off_from="08:30",
            schedule_off_to="21:00",
            clock_format="12h",
        ),
        path,
    )
    loaded = load_config(path)
    assert loaded.schedule_enabled is True
    assert loaded.schedule_off_from == "08:30"
    assert loaded.schedule_off_to == "21:00"
    assert loaded.clock_format == "12h"


def test_a_time_typed_in_twelve_hour_form_is_stored_canonically(tmp_path):
    path = tmp_path / "config.json"
    save_config(
        Config(schedule_enabled=True, schedule_off_from="1pm", schedule_off_to="11 PM"),
        path,
    )
    loaded = load_config(path)
    assert loaded.schedule_off_from == "13:00"
    assert loaded.schedule_off_to == "23:00"
    assert loaded.schedule_enabled is True


def test_an_unparseable_time_disables_the_schedule_rather_than_guessing(tmp_path):
    path = tmp_path / "config.json"
    save_config(
        Config(schedule_enabled=True, schedule_off_from="whenever", schedule_off_to="22:00"),
        path,
    )
    loaded = load_config(path)
    # Detection must never be left switched off on a value nobody chose.
    assert loaded.schedule_enabled is False
    assert loaded.schedule_off_from == "07:00"


def test_equal_start_and_end_disables_the_schedule(tmp_path):
    path = tmp_path / "config.json"
    save_config(
        Config(schedule_enabled=True, schedule_off_from="09:00", schedule_off_to="9am"),
        path,
    )
    loaded = load_config(path)
    assert loaded.schedule_enabled is False


def test_an_unknown_clock_format_falls_back_to_twenty_four_hour(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(clock_format="swatch-beats"), path)
    assert load_config(path).clock_format == "24h"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
./.venv/Scripts/python.exe -m pytest tests/test_config.py -q -k "schedule or clock_format or twelve_hour"
```

Expected: FAIL — `TypeError: Config.__init__() got an unexpected keyword argument 'schedule_enabled'`

- [ ] **Step 3: Add the config fields**

In `stfu/config.py`, add the import near the top, after `from pathlib import Path`:

```python
from stfu.clock import CLOCK_FORMATS, to_canonical
```

Then in the `Config` dataclass, after the `overlay_strikes` block and before `# Actions`, add:

```python
    # Scheduled off-hours. Times are stored canonically as 24-hour "HH:MM"
    # whatever clock_format says, so the stored value never depends on a
    # display preference and changing the format rewrites nothing.
    schedule_enabled: bool = False
    schedule_off_from: str = "07:00"
    schedule_off_to: str = "22:00"
    clock_format: str = "24h"
```

- [ ] **Step 4: Add the coercion rules**

In `_coerce`, immediately before `return cfg`, add:

```python
    if cfg.clock_format not in CLOCK_FORMATS:
        cfg.clock_format = default.clock_format

    # Normalise whatever was typed into stored form. A time that cannot be
    # parsed at all disables the schedule instead of falling back to a window
    # nobody chose -- see this function's docstring: a bad config must never
    # silently disable detection, and a guessed window would do exactly that.
    for name in ("schedule_off_from", "schedule_off_to"):
        canonical = to_canonical(getattr(cfg, name))
        if canonical is None:
            setattr(cfg, name, getattr(default, name))
            cfg.schedule_enabled = False
        else:
            setattr(cfg, name, canonical)

    # Ambiguous between a zero-length window and a whole day. The whole-day
    # reading would switch detection off permanently, so refuse both.
    if cfg.schedule_off_from == cfg.schedule_off_to:
        cfg.schedule_enabled = False
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py tests/test_boundaries.py -q`
Expected: PASS — `clock` must not have introduced a forbidden import into `config`

- [ ] **Step 6: Run the whole suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no regressions. `test_defaults_match_the_spec` still passes because it asserts named fields, not equality of the whole dataclass.

- [ ] **Step 7: Commit**

```bash
git add stfu/config.py tests/test_config.py
git commit -m "feat: store a scheduled off-hours window and a clock format"
```

---

### Task 5: Two new event types

**Files:**
- Modify: `stfu/logstore.py:13-21`
- Test: `tests/test_logstore.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_logstore.py`:

```python
def test_schedule_boundary_events_are_accepted(tmp_path):
    store = LogStore(tmp_path / "events.jsonl")
    store.append(type="schedule_suspended", session_id="s1")
    store.append(type="schedule_resumed", session_id="s1")
    kinds = [event["type"] for event in store.read_all()]
    assert kinds == ["schedule_suspended", "schedule_resumed"]
```

`LogStore.read_all()` is the reader the rest of this file already uses.

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_logstore.py -q -k schedule`
Expected: FAIL — `ValueError: unknown event type: 'schedule_suspended'`

- [ ] **Step 3: Add the event types**

In `stfu/logstore.py`, extend `EVENT_TYPES`:

```python
EVENT_TYPES = (
    "trigger",
    "session_start",
    "session_end",
    "mic_lost",
    "mic_found",
    "app_paused",
    "app_resumed",
    # Entering and leaving the configured off-hours window. Logged so the
    # report can label the gap rather than showing missing data.
    "schedule_suspended",
    "schedule_resumed",
)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_logstore.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stfu/logstore.py tests/test_logstore.py
git commit -m "feat: log entering and leaving the off-hours window"
```

---

### Task 6: The engine gate

**Files:**
- Modify: `stfu/engine.py` — imports, `__init__`, `handle_frame`, new `_update_schedule`, new property
- Test: `tests/test_engine.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py`. Note the existing `parts` fixture, `yell()` and `quiet()` helpers at the top of that file — reuse them.

```python
def scheduled(tmp_path, **overrides):
    """An engine whose config has an off-hours window in force."""
    config = Config(
        threshold_mode="manual",
        spike_threshold_dbfs=-12.0,
        cooldown_seconds=30,
        schedule_enabled=True,
        schedule_off_from="07:00",
        schedule_off_to="22:00",
        **overrides,
    )
    actions = RecordingActions()
    engine = Engine(
        config=config,
        source=FakeSource([]),
        actions=actions,
        logstore=LogStore(tmp_path / "events.jsonl"),
    )
    return engine, actions


def test_a_yell_inside_the_off_hours_window_fires_nothing(tmp_path):
    engine, actions = scheduled(tmp_path)
    yell(engine, 0.0, datetime(2026, 8, 20, 12, 0))
    assert actions.names() == []
    assert engine.scheduled_off is True


def test_a_yell_outside_the_window_still_fires(tmp_path):
    engine, actions = scheduled(tmp_path)
    yell(engine, 0.0, datetime(2026, 8, 20, 23, 0))
    assert actions.names() == [ACTION_OVERLAY]
    assert engine.scheduled_off is False


def test_a_disabled_schedule_monitors_at_every_hour(tmp_path):
    engine, actions = scheduled(tmp_path, schedule_enabled=False)
    yell(engine, 0.0, datetime(2026, 8, 20, 12, 0))
    assert actions.names() == [ACTION_OVERLAY]
    assert engine.scheduled_off is False


def test_entering_the_window_is_logged_once_not_once_per_frame(tmp_path):
    engine, _ = scheduled(tmp_path)
    quiet(engine, 0.0, datetime(2026, 8, 20, 12, 0), frames=50)
    suspends = [
        e for e in engine.logstore.read_all() if e["type"] == "schedule_suspended"
    ]
    assert len(suspends) == 1


def test_leaving_the_window_logs_a_resume_and_resets_the_detector(tmp_path):
    engine, _ = scheduled(tmp_path)
    calls = []
    real_reset = engine.detector.reset

    def spy():
        calls.append(1)
        real_reset()

    engine.detector.reset = spy

    # Inside the window, then outside it.
    quiet(engine, 0.0, datetime(2026, 8, 20, 21, 59), frames=5)
    assert calls == []
    quiet(engine, 1.0, datetime(2026, 8, 20, 22, 0), frames=5)

    # Reset on the falling edge only: the rolling windows still hold frames
    # from before the window, which may be hours old.
    assert calls == [1]
    kinds = [e["type"] for e in engine.logstore.read_all()]
    assert kinds == ["schedule_suspended", "schedule_resumed"]


def test_disabling_the_schedule_mid_window_resumes_on_the_next_frame(tmp_path):
    engine, actions = scheduled(tmp_path)
    quiet(engine, 0.0, datetime(2026, 8, 20, 12, 0), frames=5)
    assert engine.scheduled_off is True

    engine.config.schedule_enabled = False
    yell(engine, 1.0, datetime(2026, 8, 20, 12, 1))

    assert engine.scheduled_off is False
    assert actions.names() == [ACTION_OVERLAY]


def test_manual_pause_and_the_schedule_are_independent(tmp_path):
    engine, actions = scheduled(tmp_path)
    engine.pause()
    # Outside the window, but manually paused: still nothing.
    yell(engine, 0.0, datetime(2026, 8, 20, 23, 0))
    assert actions.names() == []
    engine.resume()
    yell(engine, 10.0, datetime(2026, 8, 20, 23, 1))
    assert actions.names() == [ACTION_OVERLAY]


def test_a_window_that_wraps_midnight_gates_the_small_hours(tmp_path):
    engine, actions = scheduled(
        tmp_path, schedule_off_from="23:00", schedule_off_to="06:00"
    )
    yell(engine, 0.0, datetime(2026, 8, 20, 2, 0))
    assert actions.names() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_engine.py -q -k "window or schedule or pause_and"`
Expected: FAIL — `AttributeError: 'Engine' object has no attribute 'scheduled_off'`

- [ ] **Step 3: Add the imports and state**

In `stfu/engine.py`, add to the imports:

```python
from stfu import schedule
from stfu.clock import parse_time
```

In `__init__`, after `self.paused = False`:

```python
        self._scheduled_off = False
```

- [ ] **Step 4: Add the gate to `handle_frame`**

Change the opening of `handle_frame` from:

```python
        if self.paused:
            return

        event = self.detector.push(rms, now=mono)
```

to:

```python
        if self.paused:
            return

        if self._update_schedule(wall):
            return

        event = self.detector.push(rms, now=mono)
```

- [ ] **Step 5: Add `_update_schedule` and the property**

Add after `handle_frame`, before `_fire`:

```python
    @property
    def scheduled_off(self) -> bool:
        """True while the configured off-hours window is in force.

        Named apart from the `schedule_suspended` / `schedule_resumed` event
        types so a reader never mistakes the live flag for a log record.
        """
        return self._scheduled_off

    def _update_schedule(self, wall: datetime) -> bool:
        """Track the off-hours window, returning True while it is in force.

        Evaluated from wall time on every frame rather than driven by a timer.
        A timer looks cheaper and is wrong here: this machine sleeps, and a
        boundary that falls during suspend never fires, leaving the app stuck
        in the wrong state indefinitely. A fixed delay would also drift an
        hour across a DST change. Recomputing costs two integer comparisons
        and is correct on wake, across DST, and after an NTP correction.

        Config is read every frame, so a change made in Settings takes effect
        immediately -- the same courtesy the sound folders already get.
        """
        off = False
        if self.config.schedule_enabled:
            start = parse_time(self.config.schedule_off_from)
            end = parse_time(self.config.schedule_off_to)
            # Unparseable times mean no window. _coerce should already have
            # disabled the schedule, so this is the second line of defence.
            if start is not None and end is not None:
                off = schedule.is_off(wall, start, end)

        if off != self._scheduled_off:
            self._scheduled_off = off
            if off:
                self.logstore.append(
                    type="schedule_suspended",
                    session_id=self.strikes.session_id,
                    ts=wall.isoformat(),
                )
            else:
                # Same reasoning as resume(): the rolling windows still hold
                # frames from before the window, potentially hours old, and
                # adaptive mode would compare live audio to that stale
                # baseline. Safe here only because nothing was being fed in.
                self.detector.reset()
                self.logstore.append(
                    type="schedule_resumed",
                    session_id=self.strikes.session_id,
                    ts=wall.isoformat(),
                )
        return off
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_engine.py tests/test_boundaries.py -q`
Expected: PASS. `test_boundaries` must still pass — `schedule` and `clock` are pure, so importing them into `engine` is legal.

- [ ] **Step 7: Run the whole suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no regressions

- [ ] **Step 8: Commit**

```bash
git add stfu/engine.py tests/test_engine.py
git commit -m "feat: gate detection on the scheduled off-hours window"
```

---

### Task 7: `off_windows()` in reportdata

**Files:**
- Modify: `stfu/reportdata.py`
- Test: `tests/test_reportdata.py`

`table_rows` and `csv_rows` are already fully generic (`kind=event.get("type", "")`), so the two new event types appear in the detail table and the CSV export with **no change**. Task 7 adds only the span pairing, plus a test locking in that generic behaviour so a future refactor cannot quietly drop it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reportdata.py`:

```python
def event(kind, ts):
    return {"type": kind, "ts": ts}


def test_off_windows_pairs_a_suspend_with_its_resume():
    from stfu.reportdata import off_windows

    spans = off_windows(
        [
            event("schedule_suspended", "2026-08-20T07:00:00"),
            event("trigger", "2026-08-20T08:00:00"),
            event("schedule_resumed", "2026-08-20T22:00:00"),
        ]
    )
    assert spans == [
        (datetime(2026, 8, 20, 7, 0), datetime(2026, 8, 20, 22, 0))
    ]


def test_off_windows_leaves_an_unclosed_span_open():
    from stfu.reportdata import off_windows

    # The app exited inside the window, so no resume was ever written.
    spans = off_windows([event("schedule_suspended", "2026-08-20T07:00:00")])
    assert spans == [(datetime(2026, 8, 20, 7, 0), None)]


def test_off_windows_ignores_a_resume_with_no_suspend():
    from stfu.reportdata import off_windows

    # The log is append-only and may start mid-window.
    assert off_windows([event("schedule_resumed", "2026-08-20T22:00:00")]) == []


def test_off_windows_handles_several_spans_and_unsorted_input():
    from stfu.reportdata import off_windows

    spans = off_windows(
        [
            event("schedule_resumed", "2026-08-20T22:00:00"),
            event("schedule_suspended", "2026-08-20T07:00:00"),
            event("schedule_suspended", "2026-08-21T07:00:00"),
            event("schedule_resumed", "2026-08-21T22:00:00"),
        ]
    )
    assert len(spans) == 2
    assert spans[0][0] == datetime(2026, 8, 20, 7, 0)
    assert spans[1][1] == datetime(2026, 8, 21, 22, 0)


def test_off_windows_skips_torn_lines():
    from stfu.reportdata import off_windows

    spans = off_windows(
        [
            {"type": "schedule_suspended", "ts": "not-a-timestamp"},
            event("schedule_suspended", "2026-08-20T07:00:00"),
            event("schedule_resumed", "2026-08-20T22:00:00"),
        ]
    )
    assert spans == [
        (datetime(2026, 8, 20, 7, 0), datetime(2026, 8, 20, 22, 0))
    ]


def test_schedule_events_reach_the_detail_table():
    # table_rows is generic over event type; this locks that in so the two
    # new kinds cannot be dropped by a later refactor.
    rows = table_rows(
        [
            event("schedule_suspended", "2026-08-20T07:00:00"),
            event("schedule_resumed", "2026-08-20T22:00:00"),
        ]
    )
    assert [r.kind for r in rows] == ["schedule_suspended", "schedule_resumed"]


def test_csv_export_keeps_iso_timestamps_for_schedule_events():
    rows = csv_rows([event("schedule_suspended", "2026-08-20T07:00:00")])
    assert rows[1][0] == "2026-08-20T07:00:00"
    assert rows[1][1] == "schedule_suspended"
```

Replace line 1 of `tests/test_reportdata.py`:

```python
from stfu.reportdata import csv_rows, session_summary, table_rows, trigger_points
```

with:

```python
from datetime import datetime

from stfu.reportdata import (
    csv_rows,
    off_windows,
    session_summary,
    table_rows,
    trigger_points,
)
```

Then drop the per-test `from stfu.reportdata import off_windows` lines shown above — they are written inline only to keep each test readable on its own.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_reportdata.py -q -k "off_windows or schedule or iso"`
Expected: FAIL — `ImportError: cannot import name 'off_windows' from 'stfu.reportdata'`

- [ ] **Step 3: Write the implementation**

In `stfu/reportdata.py`, add after `trigger_points`:

```python
SCHEDULE_SUSPENDED = "schedule_suspended"
SCHEDULE_RESUMED = "schedule_resumed"


def off_windows(events: list[dict]) -> list[tuple[datetime, datetime | None]]:
    """Pair schedule_suspended/schedule_resumed events into spans.

    Unpaired events are expected, not exceptional: the app can exit inside the
    window, leaving a suspend with no resume, and the log can begin mid-window,
    leaving a resume with no suspend. The first yields a span ending in None,
    meaning "still off at the end of the data"; the second is ignored.
    """
    spans: list[tuple[datetime, datetime | None]] = []
    start: datetime | None = None

    for record in sorted(events, key=lambda e: e.get("ts") or ""):
        at = _parse(record.get("ts"))
        if at is None:
            continue
        kind = record.get("type")
        if kind == SCHEDULE_SUSPENDED:
            if start is None:
                start = at
        elif kind == SCHEDULE_RESUMED and start is not None:
            spans.append((start, at))
            start = None

    if start is not None:
        spans.append((start, None))
    return spans
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_reportdata.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stfu/reportdata.py tests/test_reportdata.py
git commit -m "feat: pair off-hours boundaries into spans for the report"
```

---

### Task 8: The report window — bands and formatted times

**Files:**
- Modify: `stfu/reportui.py` — imports, `ReportWindow.__init__`, `load()`, table insert

- [ ] **Step 1: Add the imports**

In `stfu/reportui.py`, add to the imports:

```python
from matplotlib.dates import DateFormatter

from stfu.clock import format_dt
from stfu.config import Config
from stfu.reportdata import csv_rows, off_windows, session_summary, table_rows, trigger_points
```

(The last line replaces the existing `from stfu.reportdata import ...`.)

- [ ] **Step 2: Accept a Config**

Change:

```python
class ReportWindow:
    def __init__(self, master: tk.Misc, store: LogStore) -> None:
        self.master = master
        self.store = store
```

to:

```python
class ReportWindow:
    def __init__(
        self, master: tk.Misc, store: LogStore, config: Config | None = None
    ) -> None:
        self.master = master
        self.store = store
        # Optional so this window can still be constructed directly, as the
        # tests do, without wiring a real config. None means 24-hour, which is
        # what the window rendered before the setting existed.
        self.config = config
```

Add a helper method on the class:

```python
    def _clock(self) -> str:
        return self.config.clock_format if self.config else "24h"
```

- [ ] **Step 3: Draw the off-hours bands**

**Corrected since this plan's first draft.** The original instruction read
`off_windows(events)` — the session-filtered list — and that was verified broken.
On a log holding a trigger plus two schedule records, `events_for_session("s1")`
returns only `["session_start", "trigger"]`, because the engine stamps boundary
records with whatever session was open and during quiet hours there is none, so
they carry `session_id: None` and `events_for_session` matches by equality. The
bands would never have appeared, and nothing would have said so.

Two changes follow from that: read the spans from the **whole** log, and clip
them to what the displayed session spans so one night's view does not stretch
its axis across every window ever recorded.

`load()` already computes `info = session_summary(events)` further down,
immediately above `summary_label.configure(...)`. **Hoist that single line** to
just before the block below and reuse it — the block needs it, and it must not
be computed twice.

In `load()`, immediately after the `if points:` scatter block and before
`axes.set_ylabel("dBFS")`, add:

```python
            # Hoisted from below, where it feeds summary_label: the band
            # clipping needs it too, and computing it twice is waste.
            info = session_summary(events)

            # Shade the scheduled off-hours so a gap in triggers reads as
            # "the app was deliberately not listening" rather than as a dead
            # microphone or a missing log.
            #
            # Read from the whole log, not from `events`. An off-hours window
            # is a wall-clock fact about the app, not about a yelling session,
            # and the boundary records carry whatever session was open -- during
            # quiet hours, none. events_for_session() matches session_id by
            # equality, so a null-stamped record is invisible there; reading
            # the filtered list finds nothing and silently defeats the whole
            # reason these events are logged.
            #
            # Clip to this session's span. An unterminated span -- a suspend
            # with no resume, meaning the app exited inside the window -- runs
            # to the end of this session.
            if info.first_at is not None and info.last_at is not None:
                for start, end in off_windows(self.store.read_all()):
                    finish = end if end is not None else info.last_at
                    if finish < info.first_at or start > info.last_at:
                        continue
                    axes.axvspan(
                        max(start, info.first_at),
                        min(finish, info.last_at),
                        color=theme.TEXT_DIM,
                        alpha=0.18,
                        zorder=0,
                    )
```

- [ ] **Step 4: Format the chart axis**

Replace:

```python
            figure.autofmt_xdate()
```

with:

```python
            axes.xaxis.set_major_formatter(
                DateFormatter("%I:%M %p" if self._clock() == "12h" else "%H:%M")
            )
            figure.autofmt_xdate()
```

- [ ] **Step 5: Format the detail table**

Replace:

```python
                        row.at.strftime("%H:%M:%S"),
```

with:

```python
                        format_dt(row.at, self._clock(), seconds=True),
```

- [ ] **Step 6: Verify nothing broke**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no regressions. `reportui` is not in `PURE_MODULES`, so importing matplotlib and config here is fine.

- [ ] **Step 7: Manual verification**

The chart and table need eyes on them. Run the app, open **Report** from the tray, and confirm:
- the detail table's time column renders in the configured format
- the chart's x-axis labels render in the configured format
- with a schedule configured and a boundary crossed, a dim band appears

Note: `%I:%M %p` on the axis renders `01:04 PM` with a leading zero. Windows has no `%-I` for `DateFormatter`, and the axis is dense enough that the pad is not worth a custom formatter. Leave it.

- [ ] **Step 8: Commit**

```bash
git add stfu/reportui.py
git commit -m "feat: shade scheduled off-hours on the report and honour the clock format"
```

---

### Task 9: The Settings section

**Files:**
- Modify: `stfu/settingsui.py` — imports, `__init__`, `show()`, new `_add_time_entry`, `_save()`

The generic `_save()` coerces `int` and `float` fields by inspecting the current value's type and passes everything else through as a string. Time fields need their own collection, because they display in one form and store in another.

- [ ] **Step 1: Add the imports and the collection**

Add to the imports in `stfu/settingsui.py`:

```python
from stfu.clock import CLOCK_FORMATS, format_time, parse_time
```

In `__init__`, after `self._bools: dict[str, tk.BooleanVar] = {}`:

```python
        # Time fields. Kept apart from _fields because they display in the
        # operator's chosen clock format but store canonical 24-hour "HH:MM".
        self._times: dict[str, tk.StringVar] = {}
```

- [ ] **Step 2: Add the time-entry helper**

Add after `_add_entry`:

```python
    def _add_time_entry(self, parent: tk.Frame, name: str, label: str) -> None:
        """A row for a stored "HH:MM" value, shown in the chosen format.

        Input is not restricted to that format: parse_time accepts "1pm",
        "13:00" and several spellings besides, and _coerce normalises whatever
        survives back to storage form on save.
        """
        row = self._row(parent)
        tk.Label(
            row, text=label, width=26, anchor="w", bg=theme.SURFACE, fg=theme.TEXT
        ).pack(side="left", padx=(10, 0), pady=8)
        var = tk.StringVar(master=self.root, value=self._display_time(name))
        ttk.Entry(row, textvariable=var, width=14).pack(
            side="left", padx=(0, 10), pady=8
        )
        self._times[name] = var

    def _display_time(self, name: str) -> str:
        """The stored value rendered in the configured clock format."""
        minutes = parse_time(getattr(self.config, name))
        if minutes is None:
            return str(getattr(self.config, name))
        return format_time(minutes, self.config.clock_format)
```

- [ ] **Step 3: Build the section**

In `show()`, find the escalation section containing `self._add_entry(form, "nightly_reset_hour", ...)` at line 141. Add a new section after that section's last row:

```python
        self._add_section(form, "Schedule")
        self._add_bool(form, "schedule_enabled", "Disable during these hours")
        self._add_time_entry(form, "schedule_off_from", "From")
        self._add_time_entry(form, "schedule_off_to", "To")
        self._add_choice(form, "clock_format", "Clock format", CLOCK_FORMATS)
```

- [ ] **Step 4: Save and redisplay the time fields**

In `_save()`, after the `for name, var in self._bools.items():` loop and **before** `save_config(self.config)`:

```python
        # Store canonical form where it parses; leave the raw text otherwise
        # so _coerce sees it, rejects it, and disables the schedule rather
        # than this method quietly inventing a window.
        for name, var in self._times.items():
            minutes = parse_time(var.get())
            if minutes is None:
                setattr(self.config, name, var.get())
            else:
                setattr(self.config, name, f"{minutes // 60:02d}:{minutes % 60:02d}")
```

**Then fix a pre-existing bug in the same method**, because this feature turns it
from a wrong-value bug into a potential crash. `_save()` currently ends with:

```python
        save_config(self.config)
        self.config = load_config()
```

`App` hands **one** `Config` object to both `Engine` and this window
(`app.py:640`). `_save()` writes raw Entry text onto that shared object, then
rebinds only *this window's* attribute to the coerced reload -- so the engine
keeps the raw text forever. Reproduced: after a save the engine still sees
`schedule_off_from == "banana"` with `schedule_enabled == True`. Today that
already means an out-of-range `cooldown_seconds` never reaches the engine until
a restart; with this feature it would additionally mean `is_off(None, ...)`
raising `TypeError` on the audio thread. The engine now guards against that, but
the stale value is still wrong.

Replace those two lines with a copy-back onto the same object:

```python
        save_config(self.config)
        # Copy the coerced values back into the *same* object rather than
        # rebinding self.config. App hands one Config to both the engine and
        # this window, so rebinding leaves the engine holding whatever raw
        # text was typed here -- every coercion rule silently not applying
        # until the next restart.
        coerced = load_config()
        for field in fields(Config):
            setattr(self.config, field.name, getattr(coerced, field.name))
```

That needs `from dataclasses import fields` at the top of `settingsui.py`;
`Config` is already imported there.

Then in the redisplay block, add alongside the existing two loops:

```python
        for name, var in self._times.items():
            var.set(self._display_time(name))
```

Finally add a test that needs no Tk, in `tests/test_config.py`. Construct a
`Config`, set out-of-range values on it, run the same save-then-copy-back
sequence, and assert the **original object** now holds the coerced values:

```python
def test_coerced_values_can_be_copied_back_onto_a_shared_config(tmp_path):
    """settingsui._save() must not strand the engine on uncoerced values.

    App hands one Config to both the engine and the settings window, so the
    coerced reload has to be written back onto that object rather than bound
    to a fresh one.
    """
    path = tmp_path / "config.json"
    shared = Config(
        cooldown_seconds=9999, schedule_enabled=True, schedule_off_from="banana"
    )
    save_config(shared, path)

    coerced = load_config(path)
    for field in fields(Config):
        setattr(shared, field.name, getattr(coerced, field.name))

    assert shared.cooldown_seconds == 10
    assert shared.schedule_off_from == "07:00"
    assert shared.schedule_enabled is False
```

`fields` comes from `dataclasses`; add it to that test file's imports.

- [ ] **Step 5: Verify nothing broke**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Manual verification**

This is Tk, so it needs eyes. Open Settings from the tray and confirm each:

- [ ] A **SCHEDULE** section appears with a checkbox, two time entries, and a clock-format dropdown
- [ ] Type `1pm` in **From**, Save. With `clock_format` = `24h` it redisplays as `13:00`
- [ ] Switch **Clock format** to `12h`, Save. Both times redisplay as `7:00 AM` / `10:00 PM`
- [ ] Type `nonsense` in **To**, Save. The field resets to its default and **Disable during these hours** clears itself
- [ ] Set both times equal, Save. The checkbox clears itself
- [ ] Check `%LOCALAPPDATA%\STFU\config.json` — the stored times are always `"HH:MM"`, whatever the display format

- [ ] **Step 7: Commit**

```bash
git add stfu/settingsui.py
git commit -m "feat: add the Schedule settings section with format-aware time entries"
```

---

### Task 10: The tray state

**Files:**
- Modify: `stfu/tray.py:31-44`
- Create: `tests/test_tray_states.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tray_states.py`:

```python
from stfu.tray import (
    STATE_COLOURS,
    STATE_LISTENING,
    STATE_NO_MIC,
    STATE_PAUSED,
    STATE_SCHEDULED_OFF,
    STATE_TOOLTIPS,
)


def test_every_state_has_a_colour_and_a_tooltip():
    # set_state() raises on a state missing from STATE_COLOURS, and indexes
    # STATE_TOOLTIPS unguarded -- a state in one dict but not the other is a
    # crash waiting for whichever code path sets it.
    states = {STATE_LISTENING, STATE_PAUSED, STATE_NO_MIC, STATE_SCHEDULED_OFF}
    assert set(STATE_COLOURS) == states
    assert set(STATE_TOOLTIPS) == states


def test_scheduled_off_does_not_look_like_a_dead_microphone():
    # The grey no-mic icon means "broken". Scheduled-off is deliberate, so it
    # must not borrow that colour.
    assert STATE_COLOURS[STATE_SCHEDULED_OFF] != STATE_COLOURS[STATE_NO_MIC]
    assert "schedule" in STATE_TOOLTIPS[STATE_SCHEDULED_OFF].lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_tray_states.py -q`
Expected: FAIL — `ImportError: cannot import name 'STATE_SCHEDULED_OFF'`

- [ ] **Step 3: Add the state**

In `stfu/tray.py`:

```python
STATE_LISTENING = "listening"
STATE_PAUSED = "paused"
STATE_SCHEDULED_OFF = "scheduled_off"
STATE_NO_MIC = "no_mic"

STATE_COLOURS = {
    STATE_LISTENING: "#2ecc71",
    STATE_PAUSED: "#f0a500",
    # Amber already means "deliberately not listening", which is exactly what
    # this is. Sharing the colour is a deliberate simplification; the tooltips
    # differ, and a fourth colour is a two-line change if it proves confusing.
    STATE_SCHEDULED_OFF: "#f0a500",
    STATE_NO_MIC: "#888888",
}

STATE_TOOLTIPS = {
    STATE_LISTENING: "S.TFU - listening",
    STATE_PAUSED: "S.TFU - paused",
    STATE_SCHEDULED_OFF: "S.TFU - off on schedule",
    STATE_NO_MIC: "S.TFU - microphone not found",
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_tray_states.py -q`
Expected: PASS, 2 passed

- [ ] **Step 5: Commit**

```bash
git add stfu/tray.py tests/test_tray_states.py
git commit -m "feat: add a tray state for scheduled off-hours"
```

---

### Task 11: The live meter — beyond the spec, and why

> **This task is not in the approved spec.** It is added because without it the feature ships a misleading UI. Flag it to the reviewer; if they decline, skip this task and Task 12's meter line.
>
> During off-hours the meter would keep showing live levels and a threshold, so an app that is deliberately not listening looks armed. That directly contradicts the principle the spec itself cites for the tray change — the meter exists so that *"a working cooldown and a dead microphone don't look identical from the outside."* The same argument applies here with the same force.

**Files:**
- Modify: `stfu/meter.py` — `MeterReading`, `MeterState.update`
- Modify: `stfu/meterui.py` — `_refresh`
- Test: `tests/test_meter.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_meter.py`:

```python
def test_a_reading_carries_whether_the_schedule_is_off():
    state = MeterState()
    state.update(
        dbfs=-30.0,
        threshold_dbfs=-12.0,
        cooldown_remaining_s=0.0,
        mic_present=True,
        scheduled_off=True,
    )
    assert state.read().scheduled_off is True


def test_scheduled_off_defaults_to_false_for_older_callers():
    state = MeterState()
    state.update(
        dbfs=-30.0, threshold_dbfs=-12.0, cooldown_remaining_s=0.0, mic_present=True
    )
    assert state.read().scheduled_off is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_meter.py -q -k scheduled`
Expected: FAIL — `TypeError: update() got an unexpected keyword argument 'scheduled_off'`

- [ ] **Step 3: Add the field**

In `stfu/meter.py`:

```python
@dataclass(frozen=True)
class MeterReading:
    dbfs: float
    threshold_dbfs: float
    cooldown_remaining_s: float
    mic_present: bool
    # Defaulted so existing positional construction keeps working.
    scheduled_off: bool = False


_INITIAL = MeterReading(
    dbfs=MIN_DBFS,
    threshold_dbfs=0.0,
    cooldown_remaining_s=0.0,
    mic_present=True,
    scheduled_off=False,
)
```

And in `MeterState.update`:

```python
    def update(
        self,
        dbfs: float,
        threshold_dbfs: float,
        cooldown_remaining_s: float,
        mic_present: bool,
        scheduled_off: bool = False,
    ) -> None:
        reading = MeterReading(
            dbfs, threshold_dbfs, cooldown_remaining_s, mic_present, scheduled_off
        )
        with self._lock:
            self._reading = reading
```

- [ ] **Step 4: Show it in the window**

In `stfu/meterui.py`'s `_refresh`, insert a branch between the existing
`if not reading.mic_present:` block and its `else:`. A missing microphone still
wins, because that is a fault and this is not.

Change:

```python
            self._cooldown_label.configure(text="", fg=self.root.cget("bg"))
        else:
            self._level_label.configure(text=f"{reading.dbfs:.1f} dBFS")
```

to:

```python
            self._cooldown_label.configure(text="", fg=self.root.cget("bg"))
        elif reading.scheduled_off:
            # A flat bar during off-hours would look exactly like a dead
            # microphone. This window exists to stop that confusion, so it
            # says which of the two it is.
            self._level_label.configure(text="Off on schedule")
            self._canvas.coords(self._bar, 0, 0, 0, BAR_HEIGHT)
            self._canvas.coords(self._threshold_marker, 0, 0, 0, BAR_HEIGHT)
            self._threshold_label.configure(text="")
            self._cooldown_label.configure(text="Not listening", fg=theme.AMBER)
        else:
            self._level_label.configure(text=f"{reading.dbfs:.1f} dBFS")
```

`theme` is already imported in this module (`_bar_colour` returns `theme.AMBER`).

- [ ] **Step 5: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add stfu/meter.py stfu/meterui.py tests/test_meter.py
git commit -m "feat: say so in the live meter when the schedule has it switched off"
```

---

### Task 12: Wire it up in `app.py`

**Files:**
- Modify: `stfu/app.py` — imports, `_update_meter`, `_mic_found`, `_open_report`

Do this after Tasks 10 and 11.

- [ ] **Step 1: Import the new state**

Add `STATE_SCHEDULED_OFF` to the existing `from stfu.tray import (...)` block near line 100.

- [ ] **Step 2: Pass the flag to the meter and keep the tray in step**

Replace `_update_meter`:

```python
    def _update_meter(self, rms: float, now: float, mic_present: bool) -> None:
        """Feed the live meter window (F5) from the frame the capture thread
        already has -- never a second stream. See stfu/meterui.py for how the
        Tk side reads this without adding cross-thread traffic."""
        scheduled_off = self.engine.scheduled_off
        self.meter.update(
            dbfs=dbfs_from_rms(rms),
            threshold_dbfs=self.engine.detector.current_threshold(),
            cooldown_remaining_s=self.engine.detector.cooldown_remaining(now),
            mic_present=mic_present,
            scheduled_off=scheduled_off,
        )

        # The schedule changes state on a clock boundary, with no event to
        # hang a callback on, so the tray is refreshed from the frame loop.
        # Only on a change: this runs ~50 times a second, and set_state
        # rebuilds the icon bitmap every call.
        if scheduled_off != self._tray_scheduled_off:
            self._tray_scheduled_off = scheduled_off
            if not self.engine.paused:
                self.tray.set_state(
                    STATE_SCHEDULED_OFF
                    if scheduled_off
                    else (STATE_LISTENING if mic_present else STATE_NO_MIC)
                )
```

- [ ] **Step 3: Initialise the cache**

In `App.__init__`, alongside `self._mic_present`, add:

```python
        # Last scheduled-off value pushed to the tray, so the frame loop can
        # call set_state only on a change.
        self._tray_scheduled_off = False
```

- [ ] **Step 4: Do not let a returning microphone claim to be listening**

In `_mic_found`, replace:

```python
        self.tray.set_state(STATE_PAUSED if self.engine.paused else STATE_LISTENING)
```

with:

```python
        if self.engine.paused:
            state = STATE_PAUSED
        elif self.engine.scheduled_off:
            state = STATE_SCHEDULED_OFF
        else:
            state = STATE_LISTENING
        self.tray.set_state(state)
```

- [ ] **Step 5: Give the report window the config**

Replace:

```python
        ReportWindow(self.root, self.logstore).show()
```

with:

```python
        ReportWindow(self.root, self.logstore, self.config).show()
```

- [ ] **Step 6: Run the whole suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. Pay attention to `tests/test_app_wiring.py` and `tests/test_silent_death.py`, which exercise startup.

- [ ] **Step 7: Manual verification — the real proof**

Set a short window to test the boundary without waiting hours. In Settings, set **From** to two minutes ahead and **To** to four minutes ahead, tick the box, Save. Then:

- [ ] At the start boundary the tray icon turns amber and its tooltip reads *off on schedule*
- [ ] Yelling during the window does nothing at all — no sound, no overlay, no desktop drop
- [ ] The live meter says *Off on schedule*
- [ ] At the end boundary the tray returns to green and yelling triggers normally again
- [ ] The report shows a dim band over the window, and `schedule_suspended` / `schedule_resumed` rows in the detail table
- [ ] Restarting the app inside a window comes up amber, not green

- [ ] **Step 8: Commit**

```bash
git add stfu/app.py
git commit -m "feat: reflect the off-hours schedule in the tray and the meter"
```

---

### Task 13: Documentation

**Files:**
- Modify: `docs/DESIGN.md`, `README.md`, `CHANGELOG.md`

- [ ] **Step 1: DESIGN.md — the trade-offs**

Add rows to the trade-offs table (around line 363) and the storage table:

```markdown
| Off-hours evaluated per frame, not by a timer | The machine sleeps; a timer set for a boundary during suspend never fires, and a fixed delay drifts an hour across DST |
| Off-hours boundaries written to the event log | Otherwise the report shows a gap indistinguishable from a dead microphone or a lost log |
| Times stored as 24-hour "HH:MM", displayed per preference | The stored value never depends on a display setting, so changing the format rewrites nothing |
| An unparseable or zero-width window disables the schedule | `_coerce`'s rule: never leave detection switched off on a value nobody chose |
```

Add to the out-of-scope list:

```markdown
- Per-weekday or multiple off-hours windows — one window, all seven days
```

- [ ] **Step 2: README.md — Settings and the report**

In the **Settings and the tray** section, after the "Two of them are worth knowing about" list, add:

```markdown
### Scheduled off-hours

**Schedule** disables detection entirely between two times, every day. Nothing
is detected, logged, or reacted to inside the window — the tray icon goes amber
and the live meter says so.

The window is a daily one, and it wraps midnight, so `22:00`–`07:00` means
overnight. Times accept whatever you type — `1pm`, `13:00`, `1:30 PM` — and are
redisplayed in the format you pick under **Clock format**, which also drives the
times in the report. An unparseable time switches the schedule off rather than
guessing at a window, on the same principle as everything else here: a bad
setting must never quietly stop it listening.

Both boundaries are written to the event log, so the report shades the window
instead of showing a gap you have to explain to yourself later.
```

Also update the tray state list to mention amber covering both paused and scheduled-off, and the `stfu/` module map in **How it's built** with:

```
  clock.py       parsing and formatting wall-clock times
  schedule.py    the off-hours window predicate
```

- [ ] **Step 3: CHANGELOG.md — an unreleased entry**

Add above the `## [1.0.0]` heading:

```markdown
## [Unreleased]

### Added

- **Scheduled off-hours** — a daily window, set in Settings, during which
  detection is completely disabled. Nothing is detected, logged as a trigger,
  or reacted to; the tray icon goes amber and the live meter says why. The
  window wraps midnight, and both boundaries are written to the event log so
  the report shades the period rather than showing an unexplained gap.
- **A 12-hour / 24-hour clock format preference**, applied to the schedule
  fields, the report's detail table, and the report chart's axis. CSV export
  stays ISO 8601. Time entries accept `1pm`, `13:00` and several spellings
  besides, and are stored canonically regardless of the display format.

### Removed

- The stubbed USB indicator light action, which was registered but never
  backed by hardware.
```

- [ ] **Step 4: Update the README test count**

Run the suite, take the real numbers, and update the sentence in **How it's built** that currently reads `508 tests (484 passing, 24 skipped)`.

Run: `./.venv/Scripts/python.exe -m pytest -q`

- [ ] **Step 5: Commit**

```bash
git add docs/DESIGN.md README.md CHANGELOG.md
git commit -m "docs: document the scheduled off-hours window and the clock format"
```

---

## Final verification

- [ ] `./.venv/Scripts/python.exe -m pytest -q` — expect roughly **545-550 passed, 24 skipped** (about 65 new tests; the parametrised cases in Task 1 count individually)
- [ ] `./.venv/Scripts/python.exe -m pytest tests/test_boundaries.py -v` — 8 passed, `clock` and `schedule` included
- [ ] `powershell -File build.ps1` succeeds and `dist/stfu.exe` exists
- [ ] Every manual checklist in Tasks 8, 9 and 12 is ticked
- [ ] `git log --oneline` shows one commit per task, no fixup noise

## Notes for the reviewer

- **Task 11 is beyond the approved spec.** It stops the live meter looking armed during off-hours. The rationale is in the task header; skip it if you disagree.
- **`nightly_reset_hour` is deliberately untouched.** It stays a bare `0-23` integer while the schedule fields render as `7:00 AM`. The spec records this as a deferred non-goal — it is an `int`-to-`str` config migration for cosmetic gain — but it is the most likely thing to look unfinished.
- **Two tray states share amber.** Deliberate, documented in the code, and cheap to change.
