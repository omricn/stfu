import math

import numpy as np
import pytest

from stfu.levels import MIN_DBFS, dbfs_from_rms, meter_from_dbfs, rms_of_frame


def test_rms_of_silence_is_zero():
    frame = np.zeros(320, dtype=np.float32)
    assert rms_of_frame(frame) == 0.0


def test_rms_of_full_scale_square_wave_is_one():
    frame = np.ones(320, dtype=np.float32)
    assert rms_of_frame(frame) == pytest.approx(1.0)


def test_rms_of_sine_is_amplitude_over_root_two():
    t = np.linspace(0, 1, 16000, endpoint=False, dtype=np.float32)
    frame = (0.5 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
    assert rms_of_frame(frame) == pytest.approx(0.5 / math.sqrt(2), rel=1e-3)


def test_rms_of_empty_frame_is_zero():
    assert rms_of_frame(np.array([], dtype=np.float32)) == 0.0


def test_dbfs_of_full_scale_is_zero():
    assert dbfs_from_rms(1.0) == pytest.approx(0.0)


def test_dbfs_of_half_scale_is_about_minus_six():
    assert dbfs_from_rms(0.5) == pytest.approx(-6.02, abs=0.01)


def test_dbfs_of_silence_is_floor_not_negative_infinity():
    assert dbfs_from_rms(0.0) == MIN_DBFS


def test_dbfs_never_goes_below_floor():
    assert dbfs_from_rms(1e-12) == MIN_DBFS


def test_meter_maps_floor_to_zero_and_full_scale_to_hundred():
    assert meter_from_dbfs(MIN_DBFS) == 0
    assert meter_from_dbfs(0.0) == 100


def test_meter_clamps_out_of_range_values():
    assert meter_from_dbfs(-500.0) == 0
    assert meter_from_dbfs(12.0) == 100


def test_meter_midpoint_is_fifty():
    assert meter_from_dbfs(MIN_DBFS / 2) == 50
