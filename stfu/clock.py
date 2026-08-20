"""Parsing and formatting wall-clock times for display.

Times are *stored* canonically as 24-hour "HH:MM" and *displayed* in whichever
format the operator picked, so a stored value never depends on a display
preference and switching format rewrites nothing.

Parsing is deliberately lenient. Someone who has selected 12-hour display and
types "1pm" means 13:00, and refusing that would be perverse -- so every
spelling this module can understand is accepted regardless of the current
setting, and only the redisplay is canonical.
"""

from __future__ import annotations

import re
from datetime import datetime

CLOCK_FORMATS = ("12h", "24h")

MINUTES_PER_DAY = 24 * 60

# hour, optional :mm or .mm, optional am/pm with optional dots.
_TIME = re.compile(
    r"^\s*(\d{1,2})\s*(?:[:.](\d{2}))?\s*([ap]\.?m\.?)?\s*$",
    re.IGNORECASE,
)


def parse_time(text: str) -> int | None:
    """Minutes since midnight, or None if `text` is not a time.

    Accepts "7", "7:30", "07.30", "13:00", "1pm", "1 PM", "1:30 p.m.".
    """
    if not isinstance(text, str):
        return None
    match = _TIME.match(text)
    if match is None:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    suffix = (match.group(3) or "").replace(".", "").lower()

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
    """Render minutes-since-midnight for display."""
    hour, minute = divmod(minutes % MINUTES_PER_DAY, 60)
    if clock == "12h":
        suffix = "AM" if hour < 12 else "PM"
        return f"{hour % 12 or 12}:{minute:02d} {suffix}"
    return f"{hour:02d}:{minute:02d}"


def format_dt(moment: datetime, clock: str, *, seconds: bool = False) -> str:
    """Render a datetime's time of day for display."""
    if clock == "12h":
        pattern = "%I:%M:%S %p" if seconds else "%I:%M %p"
        # %I is zero-padded and Windows has no %-I; strip the pad by hand.
        rendered = moment.strftime(pattern)
        return rendered[1:] if rendered.startswith("0") else rendered
    return moment.strftime("%H:%M:%S" if seconds else "%H:%M")
