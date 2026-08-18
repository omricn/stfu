import pytest

from stfu.config import Config
from stfu.detector import Detector, TriggerEvent
from stfu.levels import rms_from_dbfs


def feed(detector, level_dbfs, frames, start=0.0, frame_s=0.02):
    """Push `frames` frames at a constant level. Returns events produced."""
    events = []
    for i in range(frames):
        event = detector.push(rms_from_dbfs(level_dbfs), now=start + i * frame_s)
        if event is not None:
            events.append(event)
    return events


def test_quiet_input_produces_nothing():
    detector = Detector(Config(threshold_mode="manual", spike_threshold_dbfs=-12.0))
    assert feed(detector, -60.0, frames=500) == []


def test_sustained_loud_input_fires_a_spike_event():
    detector = Detector(Config(threshold_mode="manual", spike_threshold_dbfs=-12.0))
    events = feed(detector, -6.0, frames=20)
    assert len(events) == 1
    assert events[0].kind == "spike"


def test_one_loud_frame_inside_a_quiet_window_does_not_fire():
    detector = Detector(Config(threshold_mode="manual", spike_threshold_dbfs=-12.0))
    # A single 20 ms frame at yell level inside a 150 ms (8 frame) window is
    # attenuated by 10*log10(1/8) = 9 dB, landing at -15 dBFS: under threshold.
    events = feed(detector, -90.0, frames=20)
    assert detector.push(rms_from_dbfs(-6.0), now=0.40) is None
    events += feed(detector, -90.0, frames=20, start=0.42)
    assert events == []


def test_a_cold_start_loud_frame_does_not_fire_on_a_partial_window():
    detector = Detector(Config(threshold_mode="manual", spike_threshold_dbfs=-12.0))
    # The very first frame is loud. With a one-frame window it would average to
    # itself and trip; the window must fill before anything can fire.
    assert detector.push(rms_from_dbfs(-6.0), now=0.0) is None


def test_event_carries_the_level_and_threshold_that_produced_it():
    detector = Detector(Config(threshold_mode="manual", spike_threshold_dbfs=-12.0))
    event = feed(detector, -6.0, frames=20)[0]
    assert isinstance(event, TriggerEvent)
    assert event.level_dbfs == pytest.approx(-6.0, abs=0.5)
    assert event.threshold_dbfs == pytest.approx(-12.0)
    assert event.at == pytest.approx(0.14, abs=0.02)


def test_cooldown_suppresses_a_second_event():
    detector = Detector(
        Config(threshold_mode="manual", spike_threshold_dbfs=-12.0, cooldown_seconds=30)
    )
    events = feed(detector, -6.0, frames=20)
    events += feed(detector, -6.0, frames=20, start=10.0)
    assert len(events) == 1


def test_a_second_event_fires_once_the_cooldown_expires():
    detector = Detector(
        Config(threshold_mode="manual", spike_threshold_dbfs=-12.0, cooldown_seconds=30)
    )
    events = feed(detector, -6.0, frames=20)
    events += feed(detector, -6.0, frames=20, start=40.0)
    assert len(events) == 2


def test_sustain_is_off_by_default():
    detector = Detector(
        Config(
            threshold_mode="manual",
            spike_threshold_dbfs=-12.0,
            sustain_threshold_dbfs=-24.0,
        )
    )
    # Loud enough for sustain, never loud enough for spike.
    assert feed(detector, -18.0, frames=300) == []


def test_sustain_fires_when_enabled():
    detector = Detector(
        Config(
            threshold_mode="manual",
            spike_threshold_dbfs=-12.0,
            sustain_enabled=True,
            sustain_threshold_dbfs=-24.0,
            sustain_window_ms=3000,
        )
    )
    events = feed(detector, -18.0, frames=300)
    assert len(events) == 1
    assert events[0].kind == "sustain"


def test_adaptive_mode_uses_the_moving_threshold():
    detector = Detector(
        Config(
            threshold_mode="adaptive",
            adaptive_delta_db=18.0,
            adaptive_min_threshold_dbfs=-40.0,
            adaptive_max_threshold_dbfs=-6.0,
        )
    )
    feed(detector, -50.0, frames=1000)          # settle a quiet baseline
    assert detector.current_threshold() == pytest.approx(-32.0)
    events = feed(detector, -20.0, frames=20, start=30.0)
    assert len(events) == 1


def test_suppression_blocks_detection_while_active():
    detector = Detector(Config(threshold_mode="manual", spike_threshold_dbfs=-12.0))
    detector.suppress_until(5.0)
    assert feed(detector, -6.0, frames=20, start=0.0) == []
    assert len(feed(detector, -6.0, frames=20, start=6.0)) == 1


def test_suppression_clears_stale_window_data():
    # Regression: windows freeze during suppression rather than tracking audio.
    # The spike window is full and loud when a trigger fires, so without
    # clearing it the first frame after suppression lifts lands in a still-loud
    # window and fires again on pre-clip audio. Only reachable when the cooldown
    # is shorter than the clip, which the config allows.
    detector = Detector(
        Config(threshold_mode="manual", spike_threshold_dbfs=-12.0, cooldown_seconds=5)
    )
    assert len(feed(detector, -6.0, frames=20)) == 1
    detector.suppress_until(10.0)
    # The 5 s cooldown expired long ago. Feeding silence must produce nothing.
    assert feed(detector, -90.0, frames=20, start=10.0) == []


def test_reset_clears_windows_and_cooldown():
    detector = Detector(Config(threshold_mode="manual", spike_threshold_dbfs=-12.0))
    feed(detector, -6.0, frames=20)
    detector.reset()
    assert len(feed(detector, -6.0, frames=20, start=1.0)) == 1


def test_wizard_mode_uses_the_fixed_threshold():
    # wizard is the shipping default and had no coverage at all.
    detector = Detector(Config())
    assert detector.current_threshold() == Config().spike_threshold_dbfs
    assert len(feed(detector, -6.0, frames=20)) == 1


def test_adaptive_mode_does_not_fire_sustain_on_room_noise():
    # Regression: the sustain threshold stayed fixed while the spike threshold
    # adapted, and the adaptive floor (-20) sits above the sustain default
    # (-24). A steady -20 dBFS room fired sustain every cooldown period, and
    # each spurious trigger swallowed the next genuine yell via the shared gate.
    detector = Detector(
        Config(
            threshold_mode="adaptive",
            sustain_enabled=True,
            spike_threshold_dbfs=-12.0,
            sustain_threshold_dbfs=-24.0,
        )
    )
    assert feed(detector, -20.0, frames=30_000) == []


def test_a_spike_trigger_blocks_a_sustain_trigger_via_the_shared_cooldown():
    detector = Detector(
        Config(
            threshold_mode="manual",
            spike_threshold_dbfs=-12.0,
            sustain_enabled=True,
            sustain_threshold_dbfs=-24.0,
            cooldown_seconds=30,
        )
    )
    events = feed(detector, -6.0, frames=200)
    assert [e.kind for e in events] == ["spike"]


def test_reset_returns_the_adaptive_threshold_to_the_floor():
    detector = Detector(
        Config(
            threshold_mode="adaptive",
            adaptive_min_threshold_dbfs=-40.0,
            adaptive_max_threshold_dbfs=-6.0,
        )
    )
    feed(detector, -50.0, frames=1000)
    assert detector.current_threshold() == pytest.approx(-32.0)
    detector.reset()
    assert detector.current_threshold() == -40.0


def test_suppression_leaves_the_adaptive_baseline_intact():
    # suppress_until clears the rolling windows but must NOT clear the baseline
    # — locking this in so nobody "fixes" it symmetrically later.
    detector = Detector(
        Config(
            threshold_mode="adaptive",
            adaptive_min_threshold_dbfs=-40.0,
            adaptive_max_threshold_dbfs=-6.0,
        )
    )
    feed(detector, -50.0, frames=1000)
    settled = detector.current_threshold()
    detector.suppress_until(100.0)
    assert detector.current_threshold() == settled


def test_suppress_until_extends_but_never_shortens():
    detector = Detector(Config(threshold_mode="manual", spike_threshold_dbfs=-12.0))
    detector.suppress_until(30.0)
    detector.suppress_until(5.0)
    assert feed(detector, -6.0, frames=20, start=10.0) == []
