import pytest

from stfu.config import Config
from stfu.firstrun import STEPS, FirstRunFlow, needs_setup


def test_a_fresh_config_needs_setup():
    assert needs_setup(Config()) is True


def test_a_config_without_a_device_needs_setup():
    assert needs_setup(Config(pin_hash="x", pin_salt="y")) is True


def test_a_config_without_a_pin_needs_setup():
    assert needs_setup(Config(device_name="Headset", device_hostapi="WASAPI")) is True


def test_a_fully_configured_config_does_not_need_setup():
    config = Config(
        device_name="Headset", device_hostapi="WASAPI", pin_hash="x", pin_salt="y"
    )
    assert needs_setup(config) is False


def test_the_flow_starts_at_the_first_step():
    assert FirstRunFlow().current == STEPS[0]


def test_advancing_moves_through_every_step_in_order():
    flow = FirstRunFlow()
    seen = [flow.current]
    while flow.advance():
        seen.append(flow.current)
    assert seen == list(STEPS)


def test_advancing_past_the_end_reports_completion():
    flow = FirstRunFlow()
    while flow.advance():
        pass
    assert flow.advance() is False
    assert flow.is_complete is True


def test_going_back_returns_to_the_previous_step():
    flow = FirstRunFlow()
    flow.advance()
    assert flow.back() is True
    assert flow.current == STEPS[0]


def test_going_back_from_the_first_step_does_nothing():
    flow = FirstRunFlow()
    assert flow.back() is False
    assert flow.current == STEPS[0]


def test_the_device_step_blocks_until_a_device_is_chosen():
    flow = FirstRunFlow()
    flow.goto("device")
    assert flow.can_advance() is False
    flow.record(device_name="Headset", device_hostapi="WASAPI")
    assert flow.can_advance() is True


def test_the_pin_step_blocks_until_a_pin_is_set():
    flow = FirstRunFlow()
    flow.goto("pin")
    assert flow.can_advance() is False
    flow.record(pin="1234")
    assert flow.can_advance() is True


def test_the_calibrate_step_blocks_until_a_threshold_exists():
    flow = FirstRunFlow()
    flow.goto("calibrate")
    assert flow.can_advance() is False
    flow.record(spike_threshold_dbfs=-14.0)
    assert flow.can_advance() is True


def test_the_optional_steps_never_block():
    flow = FirstRunFlow()
    for step in ("welcome", "test", "sounds", "autostart"):
        flow.goto(step)
        assert flow.can_advance() is True


def test_a_zero_threshold_still_lets_the_wizard_advance():
    # Regression: a truthiness check blocked here. compute_thresholds clamps to
    # MAX_THRESHOLD_DBFS = 0.0, which a yell loud enough to clip the mic really
    # does produce -- and 0.0 is falsy.
    flow = FirstRunFlow()
    flow.goto("calibrate")
    flow.record(spike_threshold_dbfs=0.0)
    assert flow.can_advance() is True


def test_an_empty_pin_still_blocks_the_wizard():
    flow = FirstRunFlow()
    flow.goto("pin")
    flow.record(pin="")
    assert flow.can_advance() is False


def test_answers_become_a_config():
    flow = FirstRunFlow()
    flow.record(
        device_name="Headset",
        device_hostapi="WASAPI",
        spike_threshold_dbfs=-14.0,
        sustain_threshold_dbfs=-26.0,
        pin="1234",
        autostart=False,
    )
    config = flow.to_config(Config())
    assert config.device_name == "Headset"
    assert config.spike_threshold_dbfs == -14.0
    assert config.autostart is False
    assert config.threshold_mode == "wizard"


def test_the_pin_is_hashed_not_stored():
    # A PIN of "1234" would make this flaky: the hash is hex, so it contains
    # "1234" by chance roughly once every thousand runs. Letters outside the
    # hex alphabet can never appear in it.
    flow = FirstRunFlow()
    flow.record(pin="swordfish")
    config = flow.to_config(Config())
    assert config.pin_hash
    assert config.pin_salt
    assert "swordfish" not in config.pin_hash
    assert "swordfish" not in config.pin_salt


def test_the_produced_config_no_longer_needs_setup():
    flow = FirstRunFlow()
    flow.record(
        device_name="Headset",
        device_hostapi="WASAPI",
        spike_threshold_dbfs=-14.0,
        pin="1234",
    )
    assert needs_setup(flow.to_config(Config())) is False


def test_goto_an_unknown_step_raises():
    with pytest.raises(ValueError):
        FirstRunFlow().goto("interpretive_dance")
