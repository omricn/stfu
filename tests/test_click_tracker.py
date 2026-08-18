import math
import random

from stfu.overlay import ClickTracker


def tracker(required=4, seed=0):
    return ClickTracker(required=required, rng=random.Random(seed))


def test_starts_with_all_clicks_remaining():
    assert tracker().remaining == 4
    assert tracker().done is False


def test_counts_down_with_each_click():
    t = tracker()
    t.click()
    assert t.remaining == 3
    t.click()
    assert t.remaining == 2


def test_is_done_only_on_the_last_click():
    t = tracker()
    assert [t.click() for _ in range(4)] == [False, False, False, True]


def test_remaining_never_goes_negative():
    t = tracker()
    for _ in range(10):
        t.click()
    assert t.remaining == 0
    assert t.done is True


def test_a_required_count_below_one_is_clamped():
    assert ClickTracker(required=0).required == 1
    assert ClickTracker(required=-5).required == 1


def test_one_click_is_a_valid_configuration():
    assert tracker(required=1).click() is True


def test_a_position_stays_inside_the_bounds():
    t = tracker()
    for _ in range(200):
        x, y = t.next_position(bounds=(800, 600), size=(120, 40))
        assert 0 <= x <= 800 - 120
        assert 0 <= y <= 600 - 40


def test_the_button_visibly_jumps_from_where_it_was():
    t = tracker()
    current = (400, 300)
    for _ in range(200):
        pos = t.next_position(
            bounds=(1920, 1080), size=(120, 40), current=current, min_move=200
        )
        assert math.hypot(pos[0] - current[0], pos[1] - current[1]) >= 200
        current = pos


def test_a_window_too_small_to_jump_still_returns_a_valid_position():
    # min_move exceeds the window diagonal, so no position can satisfy it. The
    # fallback must still land inside the bounds rather than loop or raise.
    t = tracker()
    pos = t.next_position(
        bounds=(200, 150), size=(120, 40), current=(40, 55), min_move=9999
    )
    assert 0 <= pos[0] <= 80
    assert 0 <= pos[1] <= 110


def test_the_first_position_needs_no_previous():
    x, y = tracker().next_position(bounds=(800, 600), size=(120, 40), current=None)
    assert 0 <= x <= 680


def test_a_button_larger_than_the_window_clamps_to_zero():
    assert tracker().next_position(bounds=(100, 100), size=(500, 500)) == (0, 0)


def test_positions_vary():
    t = tracker()
    seen = {t.next_position(bounds=(1920, 1080), size=(120, 40)) for _ in range(50)}
    assert len(seen) > 10
