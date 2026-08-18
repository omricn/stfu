from datetime import datetime, timedelta

from stfu.strikes import ACTION_DESKTOP_DROP, ACTION_OVERLAY, StrikeManager


def dt(day, hour, minute=0):
    return datetime(2026, 8, day, hour, minute)


def test_first_trigger_of_a_session_gets_the_overlay():
    manager = StrikeManager(reset_mode="session")
    action, index = manager.on_trigger(dt(17, 20))
    assert action == ACTION_OVERLAY
    assert index == 1


def test_second_trigger_also_gets_the_overlay_by_default():
    # The owner asked for two popups before escalating -- overlay_strikes
    # defaults to 2, so the second strike is still the overlay, not the
    # desktop drop.
    manager = StrikeManager(reset_mode="session")
    manager.on_trigger(dt(17, 20))
    action, index = manager.on_trigger(dt(17, 20, 5))
    assert action == ACTION_OVERLAY
    assert index == 2


def test_third_trigger_gets_the_desktop_drop():
    manager = StrikeManager(reset_mode="session")
    manager.on_trigger(dt(17, 20))
    manager.on_trigger(dt(17, 20, 5))
    action, index = manager.on_trigger(dt(17, 20, 10))
    assert action == ACTION_DESKTOP_DROP
    assert index == 3


def test_overlay_strikes_boundary_two_popups_then_the_drop():
    # Explicit boundary check for overlay_strikes=2: strikes 1 and 2 are the
    # overlay, strike 3 is the first desktop drop.
    manager = StrikeManager(reset_mode="session", overlay_strikes=2)
    start = dt(17, 20)
    actions = [
        manager.on_trigger(start + timedelta(seconds=5 * i))[0] for i in range(3)
    ]
    assert actions == [ACTION_OVERLAY, ACTION_OVERLAY, ACTION_DESKTOP_DROP]


def test_overlay_strikes_zero_escalates_immediately():
    manager = StrikeManager(reset_mode="session", overlay_strikes=0)
    action, index = manager.on_trigger(dt(17, 20))
    assert action == ACTION_DESKTOP_DROP
    assert index == 1


def test_the_ladder_never_climbs_back_down():
    # Step with timedelta, not by adding to the hour field: 21 + i runs past
    # hour 23 and datetime raises "hour must be in 0..23".
    manager = StrikeManager(reset_mode="session", overlay_strikes=2)
    start = dt(17, 20)
    manager.on_trigger(start)  # strike 1: overlay
    manager.on_trigger(start + timedelta(minutes=10))  # strike 2: overlay
    actions = [
        manager.on_trigger(start + timedelta(minutes=10 * (i + 3)))[0]
        for i in range(10)
    ]
    assert actions == [ACTION_DESKTOP_DROP] * 10


def test_session_mode_ignores_long_gaps():
    # overlay_strikes=1 isolates this test's actual concern (does a long gap
    # reset the session?) from the separate overlay_strikes count.
    manager = StrikeManager(reset_mode="session", overlay_strikes=1)
    manager.on_trigger(dt(17, 18))
    action, _ = manager.on_trigger(dt(17, 23))  # five hours later
    assert action == ACTION_DESKTOP_DROP


def test_end_session_resets_the_ladder():
    manager = StrikeManager(reset_mode="session")
    manager.on_trigger(dt(17, 20))
    manager.end_session()
    action, index = manager.on_trigger(dt(17, 21))
    assert action == ACTION_OVERLAY
    assert index == 1


def test_rolling_mode_resets_after_the_quiet_window():
    manager = StrikeManager(reset_mode="rolling_60m", rolling_minutes=60)
    manager.on_trigger(dt(17, 20, 0))
    action, _ = manager.on_trigger(dt(17, 21, 1))  # 61 minutes later
    assert action == ACTION_OVERLAY


def test_rolling_mode_does_not_reset_inside_the_window():
    manager = StrikeManager(
        reset_mode="rolling_60m", rolling_minutes=60, overlay_strikes=1
    )
    manager.on_trigger(dt(17, 20, 0))
    action, _ = manager.on_trigger(dt(17, 20, 59))
    assert action == ACTION_DESKTOP_DROP


def test_nightly_mode_resets_after_the_cutover_hour():
    manager = StrikeManager(reset_mode="nightly", nightly_hour=4)
    manager.on_trigger(dt(17, 23))
    action, _ = manager.on_trigger(dt(18, 5))  # next day, past 04:00
    assert action == ACTION_OVERLAY


def test_nightly_mode_treats_after_midnight_as_the_same_night():
    manager = StrikeManager(reset_mode="nightly", nightly_hour=4, overlay_strikes=1)
    manager.on_trigger(dt(17, 23))
    action, _ = manager.on_trigger(dt(18, 2))  # 02:00, before the cutover
    assert action == ACTION_DESKTOP_DROP


def test_session_id_is_stable_within_a_session():
    manager = StrikeManager(reset_mode="session")
    manager.on_trigger(dt(17, 20))
    first = manager.session_id
    manager.on_trigger(dt(17, 21))
    assert manager.session_id == first


def test_session_id_changes_after_a_reset():
    manager = StrikeManager(reset_mode="session")
    manager.on_trigger(dt(17, 20))
    first = manager.session_id
    manager.end_session()
    manager.on_trigger(dt(17, 22))
    assert manager.session_id != first


def test_strike_count_is_readable_without_triggering():
    manager = StrikeManager(reset_mode="session")
    assert manager.strike_count == 0
    manager.on_trigger(dt(17, 20))
    assert manager.strike_count == 1
