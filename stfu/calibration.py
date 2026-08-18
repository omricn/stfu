"""Turning three recorded samples into a working threshold.

Pure arithmetic, so the wizard's judgement can be tested without a microphone.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Callable

from stfu.levels import dbfs_from_rms

# How far up from the speech ceiling toward the yell peak the threshold sits.
# Biased high on purpose: a false positive on ordinary conversation destroys
# trust in the app far faster than an occasional missed yell.
YELL_BIAS = 0.6

# Where the sustain threshold sits on the same scale.
SUSTAIN_BIAS = 0.2

# Used when the yell sample is not louder than speech -- the user did not
# actually yell. Sitting above their speaking voice beats sitting below it.
FALLBACK_MARGIN_DB = 10.0

SPEECH_PERCENTILE = 0.95

MIN_THRESHOLD_DBFS = -60.0
MAX_THRESHOLD_DBFS = 0.0
DEFAULT_THRESHOLD_DBFS = -12.0
DEFAULT_SUSTAIN_DBFS = -24.0


@dataclass
class CalibrationSamples:
    quiet: list[float] = field(default_factory=list)
    speech: list[float] = field(default_factory=list)
    yell: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class CalibrationResult:
    spike_threshold_dbfs: float
    sustain_threshold_dbfs: float
    noise_floor_dbfs: float
    speech_ceiling_dbfs: float
    yell_peak_dbfs: float
    usable: bool


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def compute_thresholds(samples: CalibrationSamples) -> CalibrationResult:
    """Derive thresholds from the wizard's three samples."""
    if not samples.speech or not samples.yell:
        return CalibrationResult(
            spike_threshold_dbfs=DEFAULT_THRESHOLD_DBFS,
            sustain_threshold_dbfs=DEFAULT_SUSTAIN_DBFS,
            noise_floor_dbfs=statistics.median(samples.quiet) if samples.quiet else -90.0,
            speech_ceiling_dbfs=DEFAULT_THRESHOLD_DBFS,
            yell_peak_dbfs=DEFAULT_THRESHOLD_DBFS,
            usable=False,
        )

    noise_floor = statistics.median(samples.quiet) if samples.quiet else -90.0
    # A high percentile rather than the maximum, so one stray loud frame during
    # the speech sample cannot drag the threshold up with it.
    speech_ceiling = _percentile(samples.speech, SPEECH_PERCENTILE)
    # The yell is a brief peak in an otherwise quiet sample, so the peak is the
    # signal, not the average.
    yell_peak = max(samples.yell)

    usable = yell_peak > speech_ceiling
    if usable:
        span = yell_peak - speech_ceiling
        spike = speech_ceiling + YELL_BIAS * span
        sustain = speech_ceiling + SUSTAIN_BIAS * span
    else:
        spike = speech_ceiling + FALLBACK_MARGIN_DB
        sustain = speech_ceiling + FALLBACK_MARGIN_DB / 2

    clamp = lambda v: max(MIN_THRESHOLD_DBFS, min(MAX_THRESHOLD_DBFS, v))
    return CalibrationResult(
        spike_threshold_dbfs=round(clamp(spike), 2),
        sustain_threshold_dbfs=round(clamp(sustain), 2),
        noise_floor_dbfs=round(noise_floor, 2),
        speech_ceiling_dbfs=round(speech_ceiling, 2),
        yell_peak_dbfs=round(yell_peak, 2),
        usable=usable,
    )


def collect_sample(
    source,
    frames: int,
    on_progress: Callable[[float], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    on_level: Callable[[float], None] | None = None,
) -> list[float]:
    """Read `frames` frames from an AudioSource, in dBFS.

    Stops early if the source runs dry or the caller cancels, so the wizard's
    Back button does not have to wait out a ten-second recording.

    `on_level`, if given, is called with each frame's raw dBFS reading as it
    arrives -- separate from `on_progress` (which only ever reports how far
    through the sample the recording is, 0..1) so a caller wanting to react
    to the actual live level, such as calibrationui.py's waveform, does not
    have to instead reinterpret a completion fraction as sound. Optional and
    additive: existing callers that only pass `on_progress` are unaffected.
    """
    if frames <= 0:
        return []

    levels: list[float] = []
    for rms in source.frames():
        if is_cancelled is not None and is_cancelled():
            break
        level_dbfs = dbfs_from_rms(rms)
        levels.append(level_dbfs)
        if on_level is not None:
            on_level(level_dbfs)
        if on_progress is not None:
            on_progress(len(levels) / frames)
        if len(levels) >= frames:
            break
    return levels
