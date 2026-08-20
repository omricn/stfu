"""Does a moment fall inside the scheduled off-hours window?

Pure arithmetic on minutes since midnight. The window is half-open --
[start, end) -- so 07:00-22:00 and 22:00-07:00 tile the day with no overlap and
no gap, and a window whose start is later than its end simply wraps midnight.

The nightly-reset cutover in strikes.py leans on the same "start later than
end means wrap" trick, though it is solving an adjacent problem rather than
this one: it buckets a moment against a single boundary, where this tests
membership of a range.
"""

from __future__ import annotations

from datetime import datetime


def is_off(now: datetime, start_min: int, end_min: int) -> bool:
    """True when `now` falls inside the off-hours window.

    `start_min` and `end_min` are minutes since midnight, and the caller
    guarantees they are in range: they come from clock.parse_time, which
    cannot emit anything else, and config._coerce rejects a window before it
    reaches here. Unlike clock.format_time this does not wrap out-of-range
    input, because there is no caller that could produce it.

    Equal values are never off: the reading is ambiguous between a
    zero-length window and a whole day, and the whole-day reading would
    disable detection forever.
    """
    if start_min == end_min:
        return False
    minutes = now.hour * 60 + now.minute
    if start_min < end_min:
        return start_min <= minutes < end_min
    return minutes >= start_min or minutes < end_min
