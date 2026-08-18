import math

import pytest

from stfu.detector import RollingRms


def test_window_frames_is_computed_from_durations():
    assert RollingRms(window_ms=150, frame_ms=20).window_frames == 8
    assert RollingRms(window_ms=3000, frame_ms=20).window_frames == 150


def test_window_is_at_least_one_frame():
    assert RollingRms(window_ms=5, frame_ms=20).window_frames == 1


def test_value_before_any_push_is_zero():
    assert RollingRms(window_ms=150, frame_ms=20).value() == 0.0


def test_constant_input_gives_that_value():
    window = RollingRms(window_ms=100, frame_ms=20)
    for _ in range(5):
        window.push(0.4)
    assert window.value() == pytest.approx(0.4)


def test_averages_in_the_power_domain():
    window = RollingRms(window_ms=40, frame_ms=20)
    window.push(0.0)
    window.push(1.0)
    # Power domain: sqrt((0 + 1) / 2). Amplitude domain would give 0.5.
    assert window.value() == pytest.approx(math.sqrt(0.5))


def test_old_frames_fall_out_of_the_window():
    window = RollingRms(window_ms=40, frame_ms=20)
    window.push(1.0)
    window.push(1.0)
    assert window.value() == pytest.approx(1.0)
    window.push(0.0)
    window.push(0.0)
    assert window.value() == pytest.approx(0.0)


def test_partial_window_averages_only_what_it_has():
    window = RollingRms(window_ms=200, frame_ms=20)
    window.push(1.0)
    assert window.value() == pytest.approx(1.0)


def test_is_full_reports_whether_the_window_has_filled():
    window = RollingRms(window_ms=60, frame_ms=20)  # 3 frames
    assert window.is_full is False
    window.push(0.1)
    window.push(0.1)
    assert window.is_full is False
    window.push(0.1)
    assert window.is_full is True


def test_reset_clears_the_window():
    window = RollingRms(window_ms=100, frame_ms=20)
    window.push(1.0)
    window.reset()
    assert window.value() == 0.0
    assert window.is_full is False
