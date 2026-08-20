"""Parsing and formatting wall-clock times for display.

Times are *stored* canonically as 24-hour "HH:MM" and *displayed* in whichever
format the operator picked, so a stored value never depends on a display
preference and switching format rewrites nothing.

Parsing is deliberately lenient. Someone who has selected 12-hour display and
types "1pm" means 13:00, and refusing that would be perverse -- so every
spelling this module can understand is accepted regardless of the current
setting, and only the redisplay is canonical.

Both format_time and format_dt build 12-hour output by hand so there is one way
of doing it, rather than mixing manual construction with platform strftime calls.
"""

from __future__ import annotations

import re
from datetime import datetime

CLOCK_FORMATS = ("12h", "24h")

MINUTES_PER_DAY = 24 * 60

# Regex is used instead of strptime attempts because the parser must be
# deliberately lenient: accept both 12-hour and 24-hour input regardless of
# the operator's display preference, with flexible separators (: or .), and
# optional leading zeros. strptime cannot do this without creating multiple
# format attempts and masking actual parsing errors under exception handling.
_TIME = re.compile(
    r"^\s*(?P<hour>\d{1,2})\s*(?:[:.](?P<minute>\d{2}))?\s*(?P<suffix>[ap]\.?m\.?)?\s*$",
    re.IGNORECASE,
)


def parse_time(text: object) -> int | None:
    """Minutes since midnight, or None if `text` is not a time.

    Accepts "7", "7:30", "07.30", "13:00", "1pm", "1 PM", "1:30 p.m.".
    Deliberately handles non-string input (returns None) since values may be
    hand-edited in config.json.
    """
    if not isinstance(text, str):
        return None
    match = _TIME.match(text)
    if match is None:
        return None

    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    suffix = (match.group("suffix") or "").replace(".", "").lower()

    if minute > 59:
        return None
    if suffix:
        # A 12-hour clock has no hour 0 and no hour 13.
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12
        if suffix == "pm":
            hour += 12
    elif hour > 23:
        return None

    return hour * 60 + minute


def to_canonical(text: str) -> str | None:
    """Normalise any accepted spelling to the stored "HH:MM" form."""
    minutes = parse_time(text)
    if minutes is None:
        return None
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def format_time(minutes: int, clock: str) -> str:
    """Render minutes-since-midnight for display.

    Wraps out-of-range input modulo MINUTES_PER_DAY as a defensive measure.
    The clock argument defaults to 24-hour format for any value other than "12h",
    since 24-hour format is unambiguous and cannot be misread.
    """
    hour, minute = divmod(minutes % MINUTES_PER_DAY, 60)
    if clock == "12h":
        suffix = "AM" if hour < 12 else "PM"
        return f"{hour % 12 or 12}:{minute:02d} {suffix}"
    return f"{hour:02d}:{minute:02d}"


def format_dt(moment: datetime, clock: str, *, seconds: bool = False) -> str:
    """Render a datetime's time of day for display."""
    if clock == "12h":
        hour = moment.hour % 12 or 12
        minute = moment.minute
        second = moment.second
        suffix = "AM" if moment.hour < 12 else "PM"
        if seconds:
            return f"{hour}:{minute:02d}:{second:02d} {suffix}"
        return f"{hour}:{minute:02d} {suffix}"
    return moment.strftime("%H:%M:%S" if seconds else "%H:%M")
