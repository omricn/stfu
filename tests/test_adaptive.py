import pytest

from stfu.detector import AdaptiveThreshold


def make(**kwargs):
    params = dict(
        delta_db=18.0,
        min_threshold_dbfs=-20.0,
        max_threshold_dbfs=-6.0,
        baseline_minutes=10,
        frame_ms=20,
    )
    params.update(kwargs)
    return AdaptiveThreshold(**params)


def test_starts_at_the_floor_before_any_samples():
    assert make().threshold() == -20.0


def test_quiet_room_holds_the_threshold_at_the_floor():
    adaptive = make()
    for _ in range(1000):
        adaptive.push(-70.0)
    assert adaptive.threshold() == -20.0


def test_noisy_room_raises_the_threshold_above_the_floor():
    adaptive = make()
    for _ in range(1000):
        adaptive.push(-30.0)
    assert adaptive.threshold() == pytest.approx(-12.0)


def test_threshold_is_capped_by_the_ceiling():
    adaptive = make()
    for _ in range(1000):
        adaptive.push(-10.0)
    # baseline + 18 would be +8; the ceiling holds it at -6.
    assert adaptive.threshold() == -6.0


def test_loud_frames_are_excluded_so_the_threshold_cannot_drift_up():
    adaptive = make()
    for _ in range(1000):
        adaptive.push(-30.0)
    settled = adaptive.threshold()
    # Twenty minutes of continuous yelling above the threshold.
    for _ in range(60_000):
        adaptive.push(-5.0)
    assert adaptive.threshold() == pytest.approx(settled)


def test_baseline_forgets_samples_older_than_the_window():
    # Forgetting is observable in the downward direction: the room gets quieter
    # and old loud samples age out of the deque.
    adaptive = make(baseline_minutes=1)  # 3000 frames at 20 ms
    for _ in range(3000):
        adaptive.push(-30.0)
    assert adaptive.threshold() == pytest.approx(-12.0)
    for _ in range(3000):
        adaptive.push(-70.0)
    assert adaptive.threshold() == -20.0


def test_a_loud_room_can_still_establish_a_baseline():
    # Regression: exclusion used to compare against the *clamped* threshold, so
    # with an empty window nothing above the floor could ever be admitted and
    # the baseline stayed empty forever.
    adaptive = make()
    for _ in range(1000):
        adaptive.push(-15.0)
    assert adaptive.threshold() == pytest.approx(-6.0)


def test_the_baseline_ratchets_downward_only():
    # Deliberate consequence of the exclusion guard: a room that gets louder
    # does not raise the threshold, because those frames are what the guard
    # exists to reject. Documented here so it is not "fixed" by accident.
    adaptive = make(min_threshold_dbfs=-40.0)
    for _ in range(1000):
        adaptive.push(-50.0)
    settled = adaptive.threshold()
    assert settled == pytest.approx(-32.0)  # above the floor, so not a trivial pass
    for _ in range(1000):
        adaptive.push(-25.0)
    assert adaptive.threshold() == settled


def test_uses_the_median_so_a_few_outliers_do_not_move_it():
    adaptive = make()
    for _ in range(999):
        adaptive.push(-30.0)
    adaptive.push(-25.0)
    assert adaptive.threshold() == pytest.approx(-12.0)


def test_reset_returns_to_the_floor():
    adaptive = make()
    for _ in range(1000):
        adaptive.push(-30.0)
    adaptive.reset()
    assert adaptive.threshold() == -20.0


def test_baseline_is_decimated_to_keep_the_median_cheap():
    # median() sorts a full copy on every recompute. Undecimated, a 10-minute
    # window at 20 ms frames would sort 30,000 floats 50 times a second.
    adaptive = make()
    for _ in range(30_000):
        adaptive.push(-50.0)
    assert len(adaptive._samples) <= AdaptiveThreshold.MAX_BASELINE_SAMPLES
