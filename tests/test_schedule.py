from datetime import datetime

from stfu.schedule import is_off


def at(hour, minute=0):
    return datetime(2026, 8, 20, hour, minute)


DAY = 7 * 60      # 07:00
NIGHT = 22 * 60   # 22:00


def test_a_window_inside_one_day():
    # off from 07:00 to 22:00
    assert is_off(at(6, 59), DAY, NIGHT) is False
    assert is_off(at(7, 0), DAY, NIGHT) is True
    assert is_off(at(12, 0), DAY, NIGHT) is True
    assert is_off(at(21, 59), DAY, NIGHT) is True
    assert is_off(at(22, 0), DAY, NIGHT) is False
    assert is_off(at(23, 30), DAY, NIGHT) is False


def test_a_window_that_wraps_midnight():
    # off from 22:00 to 07:00
    assert is_off(at(21, 59), NIGHT, DAY) is False
    assert is_off(at(22, 0), NIGHT, DAY) is True
    assert is_off(at(23, 59), NIGHT, DAY) is True
    assert is_off(at(0, 0), NIGHT, DAY) is True
    assert is_off(at(6, 59), NIGHT, DAY) is True
    assert is_off(at(7, 0), NIGHT, DAY) is False
    assert is_off(at(12, 0), NIGHT, DAY) is False


def test_the_window_is_half_open_so_the_two_halves_tile_the_day():
    # Every minute is off in exactly one of the two complementary windows.
    for minutes in range(0, 24 * 60):
        moment = at(minutes // 60, minutes % 60)
        inside = is_off(moment, DAY, NIGHT)
        outside = is_off(moment, NIGHT, DAY)
        assert inside != outside, f"{moment} is in both or neither"


def test_a_non_wrapping_window_covers_exactly_its_own_minutes():
    off = sum(
        1 for m in range(0, 24 * 60) if is_off(at(m // 60, m % 60), DAY, NIGHT)
    )
    assert off == NIGHT - DAY == 900


def test_equal_start_and_end_is_never_off():
    # Ambiguous between zero-length and 24 hours. config._coerce rejects it
    # before it reaches here; this is the defensive second answer, and it is
    # the safe one -- 24 hours off would disable detection permanently.
    for hour in (0, 7, 23):
        assert is_off(at(hour), hour * 60, hour * 60) is False


def test_seconds_within_the_boundary_minute_do_not_matter():
    assert is_off(datetime(2026, 8, 20, 22, 0, 59), NIGHT, DAY) is True
    assert is_off(datetime(2026, 8, 20, 6, 59, 59), NIGHT, DAY) is True
