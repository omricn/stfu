"""Conversions between audio frames, linear RMS, dBFS, and a display meter."""

from __future__ import annotations

import math

import numpy as np

# Anything quieter than this is treated as silence. Prevents log(0) and keeps
# the display meter on a fixed, comparable scale between sessions.
MIN_DBFS = -90.0


def rms_of_frame(frame: np.ndarray) -> float:
    """Linear root-mean-square amplitude of a float frame, 0.0 to 1.0."""
    if frame.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))


def dbfs_from_rms(rms: float) -> float:
    """Convert linear RMS to dBFS, floored at MIN_DBFS."""
    if rms <= 0.0:
        return MIN_DBFS
    return max(MIN_DBFS, 20.0 * math.log10(rms))


def rms_from_dbfs(level_dbfs: float) -> float:
    """Inverse of dbfs_from_rms. Used by tests and by threshold arithmetic."""
    return 10.0 ** (level_dbfs / 20.0)


def meter_from_dbfs(level_dbfs: float) -> int:
    """Map dBFS onto a 0-100 integer for display. Never used for decisions."""
    clamped = max(MIN_DBFS, min(0.0, level_dbfs))
    return round((clamped - MIN_DBFS) / (0.0 - MIN_DBFS) * 100)
