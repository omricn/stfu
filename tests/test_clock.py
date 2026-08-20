from datetime import datetime

import pytest

from stfu.clock import CLOCK_FORMATS, MINUTES_PER_DAY, format_dt, format_time, parse_time, to_canonical


@pytest.mark.parametrize(
    "text,expected",
    [
        ("7", 420),
        ("7:30", 450),
        ("07:30", 450),
        ("07.30", 450),
        ("13:00", 780),
        ("1pm", 780),
        ("1 PM", 780),
        ("1:30pm", 810),
        ("1:30 p.m.", 810),
        ("12am", 0),
        ("12:00 AM", 0),
        ("12pm", 720),
        ("  7:05  ", 425),
        ("23:59", 1439),
    ],
)
def test_parse_time_accepts_every_spelling_a_user_might_type(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "   ", "abc", "25:00", "12:60", "13pm", "0pm", "7:5", "-1:00", "1:00:00"],
)
def test_parse_time_rejects_what_is_not_a_time(text):
    assert parse_time(text) is None


def test_parse_time_rejects_non_strings():
    assert parse_time(None) is None
    assert parse_time(700) is None


def test_to_canonical_normalises_to_stored_form():
    assert to_canonical("1pm") == "13:00"
    assert to_canonical("7") == "07:00"
    assert to_canonical("12am") == "00:00"
    assert to_canonical("nonsense") is None


def test_format_time_renders_both_formats():
    assert format_time(420, "24h") == "07:00"
    assert format_time(420, "12h") == "7:00 AM"
    assert format_time(1320, "24h") == "22:00"
    assert format_time(1320, "12h") == "10:00 PM"


def test_format_time_gets_midnight_and_noon_right():
    # The classic 12-hour bug: hour 0 must read 12 AM, not 0 AM.
    assert format_time(0, "12h") == "12:00 AM"
    assert format_time(720, "12h") == "12:00 PM"
    assert format_time(0, "24h") == "00:00"


def test_format_time_wraps_out_of_range_input():
    # Wraparound at day boundary is defensive but intentional.
    assert format_time(MINUTES_PER_DAY, "24h") == "00:00"
    assert format_time(1440, "12h") == "12:00 AM"


def test_format_time_defaults_unknown_clock_to_24h():
    # 24-hour format is the deliberate fallback for unrecognized clock values,
    # since it is unambiguous and cannot be misread.
    assert format_time(60, "bogus") == "01:00"
    assert format_time(780, "unknown") == "13:00"


def test_every_minute_of_the_day_survives_a_round_trip():
    # The strongest guarantee available here: whatever we display, we can
    # read back. A display format that cannot be re-parsed would silently
    # reset the user's schedule the next time they saved Settings.
    for clock in CLOCK_FORMATS:
        for minutes in range(0, MINUTES_PER_DAY):
            rendered = format_time(minutes, clock)
            assert parse_time(rendered) == minutes, f"{clock} {minutes} -> {rendered}"


def test_format_dt_renders_time_of_day():
    moment = datetime(2026, 8, 20, 13, 4, 22)
    assert format_dt(moment, "24h") == "13:04"
    assert format_dt(moment, "24h", seconds=True) == "13:04:22"
    assert format_dt(moment, "12h") == "1:04 PM"
    assert format_dt(moment, "12h", seconds=True) == "1:04:22 PM"


def test_format_dt_renders_with_seconds_both_hour_sizes():
    # Test both single-digit and double-digit hours with seconds=True.
    single_digit = datetime(2026, 8, 20, 1, 4, 22)
    double_digit = datetime(2026, 8, 20, 10, 4, 22)
    assert format_dt(single_digit, "12h", seconds=True) == "1:04:22 AM"
    assert format_dt(double_digit, "12h", seconds=True) == "10:04:22 AM"


def test_format_dt_keeps_a_double_digit_hour_intact():
    # Double-digit hours in 12-hour format are rendered without padding.
    moment = datetime(2026, 8, 20, 10, 4, 0)
    assert format_dt(moment, "12h") == "10:04 AM"


def test_format_dt_defaults_unknown_clock_to_24h():
    # 24-hour format is the deliberate fallback for unrecognized clock values,
    # since it is unambiguous and cannot be misread.
    moment = datetime(2026, 8, 20, 13, 4, 22)
    assert format_dt(moment, "bogus") == "13:04"
    assert format_dt(moment, "bogus", seconds=True) == "13:04:22"
    assert format_dt(moment, "unknown") == "13:04"
    assert format_dt(moment, "unknown", seconds=True) == "13:04:22"
