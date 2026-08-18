"""A thread-safe snapshot of the live audio level (F5).

Written by the capture thread on every frame; read by the meter window on
its own slower timer. No Tk, no audio library -- safe to import from either
side of that boundary.

Plain attribute writes are already atomic in CPython, but the four fields
that make up one reading (level, threshold, cooldown, mic presence) have to
be read *together* or a display could pair one frame's level with another
frame's cooldown -- harmless most of the time, but this window exists
specifically so a suppressed yell reads as suppressed rather than ignored,
and a torn read could show a stale cooldown next to a fresh level at exactly
the moment that distinction matters. A lock removes the possibility instead
of relying on interpreter internals to happen to be safe.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from stfu.levels import MIN_DBFS


@dataclass(frozen=True)
class MeterReading:
    dbfs: float
    threshold_dbfs: float
    cooldown_remaining_s: float
    mic_present: bool


_INITIAL = MeterReading(
    dbfs=MIN_DBFS, threshold_dbfs=0.0, cooldown_remaining_s=0.0, mic_present=True
)


class MeterState:
    """Holds the single most recent MeterReading."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reading = _INITIAL

    def update(
        self,
        dbfs: float,
        threshold_dbfs: float,
        cooldown_remaining_s: float,
        mic_present: bool,
    ) -> None:
        reading = MeterReading(dbfs, threshold_dbfs, cooldown_remaining_s, mic_present)
        with self._lock:
            self._reading = reading

    def read(self) -> MeterReading:
        with self._lock:
            return self._reading
