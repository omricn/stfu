import pytest

from stfu.calibration import CalibrationSamples, compute_thresholds


def samples(quiet, speech, yell):
    return CalibrationSamples(quiet=quiet, speech=speech, yell=yell)


def test_the_threshold_sits_between_speech_and_yell():
    result = compute_thresholds(samples([-70.0] * 10, [-30.0] * 10, [-8.0] * 5))
    assert -30.0 < result.spike_threshold_dbfs < -8.0


def test_the_threshold_is_biased_toward_the_yell():
    # 0.6 of the way up from the speech ceiling: a false positive on ordinary
    # conversation destroys trust faster than a missed yell.
    result = compute_thresholds(samples([-70.0] * 10, [-30.0] * 10, [-10.0] * 5))
    assert result.spike_threshold_dbfs == pytest.approx(-18.0, abs=0.5)


def test_the_sustain_threshold_sits_below_the_spike_threshold():
    result = compute_thresholds(samples([-70.0] * 10, [-30.0] * 10, [-10.0] * 5))
    assert result.sustain_threshold_dbfs < result.spike_threshold_dbfs


def test_speech_uses_a_high_percentile_not_the_maximum():
    # One stray loud frame during the speech sample must not drag the whole
    # threshold up with it.
    quiet = [-70.0] * 10
    yell = [-10.0] * 5
    normal = compute_thresholds(samples(quiet, [-30.0] * 100, yell))
    with_outlier = compute_thresholds(samples(quiet, [-30.0] * 99 + [-11.0], yell))
    assert with_outlier.spike_threshold_dbfs == pytest.approx(
        normal.spike_threshold_dbfs, abs=1.0
    )


def test_the_yell_uses_its_peak():
    quiet = [-70.0] * 10
    speech = [-30.0] * 10
    # A yell is a brief peak in a mostly-quiet sample; the peak is the signal.
    result = compute_thresholds(samples(quiet, speech, [-70.0] * 50 + [-6.0]))
    assert result.spike_threshold_dbfs > -30.0


def test_a_yell_quieter_than_speech_falls_back_to_a_margin():
    # The user did not actually yell. Rather than producing a threshold below
    # their speaking voice -- which would fire constantly -- sit above it.
    result = compute_thresholds(samples([-70.0] * 10, [-30.0] * 10, [-35.0] * 5))
    assert result.spike_threshold_dbfs > -30.0
    assert result.usable is False


def test_a_good_calibration_is_marked_usable():
    result = compute_thresholds(samples([-70.0] * 10, [-30.0] * 10, [-8.0] * 5))
    assert result.usable is True


def test_empty_samples_produce_the_defaults():
    result = compute_thresholds(samples([], [], []))
    assert result.usable is False
    assert result.spike_threshold_dbfs == -12.0


def test_the_threshold_is_clamped_to_a_sane_range():
    result = compute_thresholds(samples([-90.0] * 10, [-89.0] * 10, [-88.0] * 5))
    assert -60.0 <= result.spike_threshold_dbfs <= 0.0


def test_the_quiet_sample_is_reported_as_the_noise_floor():
    result = compute_thresholds(samples([-70.0] * 10, [-30.0] * 10, [-8.0] * 5))
    assert result.noise_floor_dbfs == pytest.approx(-70.0, abs=1.0)
