from datetime import datetime, timedelta

import pytest

from stfu.audio import FakeSource
from stfu.config import Config
from stfu.engine import Engine
from stfu.levels import rms_from_dbfs
from stfu.logstore import LogStore
from stfu.strikes import ACTION_DESKTOP_DROP, ACTION_OVERLAY


class RecordingActions:
    """Stands in for the real action registry. Records what was fired."""

    def __init__(self):
        self.fired = []

    def fire(self, name, event):
        self.fired.append(name)
        return None  # no sound clip played

    def names(self):
        return self.fired


@pytest.fixture
def parts(tmp_path):
    config = Config(
        threshold_mode="manual", spike_threshold_dbfs=-12.0, cooldown_seconds=30
    )
    actions = RecordingActions()
    engine = Engine(
        config=config,
        source=FakeSource([]),
        actions=actions,
        logstore=LogStore(tmp_path / "events.jsonl"),
    )
    return engine, actions


def yell(engine, start_mono, start_wall, frames=20, level=-6.0):
    for i in range(frames):
        engine.handle_frame(
            rms_from_dbfs(level),
            mono=start_mono + i * 0.02,
            wall=start_wall + timedelta(seconds=i * 0.02),
        )


def quiet(engine, start_mono, start_wall, frames=100):
    yell(engine, start_mono, start_wall, frames=frames, level=-70.0)


def test_a_quiet_stream_fires_nothing(parts):
    engine, actions = parts
    quiet(engine, 0.0, datetime(2026, 8, 17, 20, 0))
    assert actions.names() == []


def test_first_yell_fires_the_overlay(parts):
    engine, actions = parts
    yell(engine, 0.0, datetime(2026, 8, 17, 20, 0))
    assert actions.names() == [ACTION_OVERLAY]


def test_second_yell_fires_the_desktop_drop(parts):
    engine, actions = parts
    base = datetime(2026, 8, 17, 20, 0)
    yell(engine, 0.0, base)
    yell(engine, 60.0, base + timedelta(seconds=60))
    assert actions.names() == [ACTION_OVERLAY, ACTION_DESKTOP_DROP]


def test_later_yells_keep_firing_the_desktop_drop(parts):
    engine, actions = parts
    base = datetime(2026, 8, 17, 20, 0)
    for i in range(5):
        yell(engine, i * 60.0, base + timedelta(seconds=i * 60))
    assert actions.names() == [ACTION_OVERLAY] + [ACTION_DESKTOP_DROP] * 4


def test_yells_inside_the_cooldown_fire_nothing(parts):
    engine, actions = parts
    base = datetime(2026, 8, 17, 20, 0)
    yell(engine, 0.0, base)
    yell(engine, 5.0, base + timedelta(seconds=5))
    assert actions.names() == [ACTION_OVERLAY]


def test_each_trigger_is_logged_with_its_details(parts):
    engine, actions = parts
    yell(engine, 0.0, datetime(2026, 8, 17, 20, 0))
    triggers = [e for e in engine.logstore.read_all() if e["type"] == "trigger"]
    assert len(triggers) == 1
    assert triggers[0]["action"] == ACTION_OVERLAY
    assert triggers[0]["strike_index"] == 1
    assert triggers[0]["trigger"] == "spike"
    assert triggers[0]["level_dbfs"] == pytest.approx(-6.0, abs=0.5)
    assert triggers[0]["session_id"]


def test_session_start_is_logged_once(parts):
    engine, _ = parts
    base = datetime(2026, 8, 17, 20, 0)
    yell(engine, 0.0, base)
    yell(engine, 60.0, base + timedelta(seconds=60))
    starts = [e for e in engine.logstore.read_all() if e["type"] == "session_start"]
    assert len(starts) == 1


def test_stopping_logs_the_session_end(parts):
    engine, _ = parts
    yell(engine, 0.0, datetime(2026, 8, 17, 20, 0))
    engine.stop()
    ends = [e for e in engine.logstore.read_all() if e["type"] == "session_end"]
    assert len(ends) == 1


def test_stopping_without_any_trigger_logs_no_session_end(parts):
    engine, _ = parts
    engine.stop()
    assert engine.logstore.read_all() == []


def test_mic_loss_and_return_are_logged(parts):
    engine, _ = parts
    engine.on_mic_lost()
    engine.on_mic_found()
    types = [e["type"] for e in engine.logstore.read_all()]
    assert types == ["mic_lost", "mic_found"]


def test_pausing_blocks_detection(parts):
    engine, actions = parts
    engine.pause()
    yell(engine, 0.0, datetime(2026, 8, 17, 20, 0))
    assert actions.names() == []


def test_resuming_restores_detection(parts):
    engine, actions = parts
    base = datetime(2026, 8, 17, 20, 0)
    engine.pause()
    yell(engine, 0.0, base)
    engine.resume()
    yell(engine, 60.0, base + timedelta(seconds=60))
    assert actions.names() == [ACTION_OVERLAY]


def test_a_clip_duration_suppresses_detection_for_its_length(tmp_path):
    class SoundActions(RecordingActions):
        def fire(self, name, event):
            self.fired.append(name)
            return 3.0  # the clip runs three seconds

    config = Config(
        threshold_mode="manual", spike_threshold_dbfs=-12.0, cooldown_seconds=1
    )
    actions = SoundActions()
    engine = Engine(
        config=config,
        source=FakeSource([]),
        actions=actions,
        logstore=LogStore(tmp_path / "events.jsonl"),
    )
    base = datetime(2026, 8, 17, 20, 0)
    yell(engine, 0.0, base)
    # Two seconds later the cooldown has expired but the clip is still playing.
    yell(engine, 2.0, base + timedelta(seconds=2))
    assert actions.names() == [ACTION_OVERLAY]


def test_an_action_that_raises_does_not_kill_the_engine(tmp_path):
    class ExplodingActions(RecordingActions):
        def fire(self, name, event):
            self.fired.append(name)
            raise RuntimeError("overlay failed to open")

    actions = ExplodingActions()
    engine = Engine(
        config=Config(threshold_mode="manual", spike_threshold_dbfs=-12.0),
        source=FakeSource([]),
        actions=actions,
        logstore=LogStore(tmp_path / "events.jsonl"),
    )
    base = datetime(2026, 8, 17, 20, 0)
    yell(engine, 0.0, base)
    yell(engine, 60.0, base + timedelta(seconds=60))
    assert actions.names() == [ACTION_OVERLAY, ACTION_DESKTOP_DROP]


def test_a_trigger_is_logged_before_the_action_runs(tmp_path):
    # The overlay action blocks until four clicks, potentially for minutes. If
    # the log write came afterwards, a kill while the overlay was open would
    # lose the strike entirely even though the child saw it.
    seen = {}
    store = LogStore(tmp_path / "events.jsonl")

    class InspectingActions(RecordingActions):
        def fire(self, name, event):
            self.fired.append(name)
            seen["triggers"] = [
                e for e in store.read_all() if e["type"] == "trigger"
            ]
            return None

    engine = Engine(
        config=Config(threshold_mode="manual", spike_threshold_dbfs=-12.0),
        source=FakeSource([]),
        actions=InspectingActions(),
        logstore=store,
    )
    yell(engine, 0.0, datetime(2026, 8, 17, 20, 0))
    assert len(seen["triggers"]) == 1


def test_the_trigger_timestamp_is_the_yell_not_the_write(parts):
    engine, _ = parts
    yell(engine, 0.0, datetime(2026, 8, 17, 20, 0))
    trigger = [e for e in engine.logstore.read_all() if e["type"] == "trigger"][0]
    # The spike window fills on the 8th frame: 20:00:00 + 7 * 0.02s.
    assert trigger["ts"].startswith("2026-08-17T20:00:00")


def test_a_session_rollover_logs_its_own_session_start(tmp_path):
    # rolling_60m mints a new session id mid-run. A bare "already logged" bool
    # suppressed the new session's session_start, orphaning its triggers.
    store = LogStore(tmp_path / "events.jsonl")
    engine = Engine(
        config=Config(
            threshold_mode="manual",
            spike_threshold_dbfs=-12.0,
            cooldown_seconds=30,
            session_reset_mode="rolling_60m",
            rolling_reset_minutes=60,
        ),
        source=FakeSource([]),
        actions=RecordingActions(),
        logstore=store,
    )
    base = datetime(2026, 8, 17, 20, 0)
    yell(engine, 0.0, base)
    yell(engine, 4000.0, base + timedelta(minutes=61))
    events = store.read_all()
    starts = {e["session_id"] for e in events if e["type"] == "session_start"}
    triggers = {e["session_id"] for e in events if e["type"] == "trigger"}
    assert len(starts) == 2
    assert triggers == starts


def test_a_session_rollover_closes_the_previous_session(tmp_path):
    store = LogStore(tmp_path / "events.jsonl")
    engine = Engine(
        config=Config(
            threshold_mode="manual",
            spike_threshold_dbfs=-12.0,
            cooldown_seconds=30,
            session_reset_mode="rolling_60m",
            rolling_reset_minutes=60,
        ),
        source=FakeSource([]),
        actions=RecordingActions(),
        logstore=store,
    )
    base = datetime(2026, 8, 17, 20, 0)
    yell(engine, 0.0, base)
    yell(engine, 4000.0, base + timedelta(minutes=61))
    ends = [e for e in store.read_all() if e["type"] == "session_end"]
    assert len(ends) == 1
    assert ends[0]["session_id"] == "2026-08-17T20:00:00"


def test_pausing_twice_logs_one_event(parts):
    engine, _ = parts
    engine.pause()
    engine.pause()
    assert [e["type"] for e in engine.logstore.read_all()] == ["app_paused"]


def test_resuming_when_not_paused_is_a_no_op(parts):
    # A redundant resume must not reset the detector: that would clear the
    # rolling windows and blind detection until they refill.
    engine, _ = parts
    yell(engine, 0.0, datetime(2026, 8, 17, 20, 0))
    engine.resume()
    assert not [e for e in engine.logstore.read_all() if e["type"] == "app_resumed"]
