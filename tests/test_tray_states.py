from stfu.tray import (
    STATE_COLOURS,
    STATE_LISTENING,
    STATE_NO_MIC,
    STATE_PAUSED,
    STATE_SCHEDULED_OFF,
    STATE_TOOLTIPS,
)


def test_every_state_has_a_colour_and_a_tooltip():
    # set_state() raises on a state missing from STATE_COLOURS, and indexes
    # STATE_TOOLTIPS unguarded -- a state in one dict but not the other is a
    # crash waiting for whichever code path sets it.
    states = {STATE_LISTENING, STATE_PAUSED, STATE_NO_MIC, STATE_SCHEDULED_OFF}
    assert set(STATE_COLOURS) == states
    assert set(STATE_TOOLTIPS) == states


def test_scheduled_off_does_not_look_like_a_dead_microphone():
    # The grey no-mic icon means "broken". Scheduled-off is deliberate, so it
    # must not borrow that colour.
    assert STATE_COLOURS[STATE_SCHEDULED_OFF] != STATE_COLOURS[STATE_NO_MIC]
    assert "schedule" in STATE_TOOLTIPS[STATE_SCHEDULED_OFF].lower()
