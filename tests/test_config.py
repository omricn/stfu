import json
from dataclasses import fields

import pytest

from stfu.config import (
    Config,
    hash_pin,
    load_config,
    reset_config,
    save_config,
    verify_pin,
)


def test_defaults_match_the_spec():
    cfg = Config()
    assert cfg.threshold_mode == "wizard"
    assert cfg.spike_window_ms == 150
    assert cfg.sustain_enabled is False
    assert cfg.cooldown_seconds == 10
    assert cfg.session_reset_mode == "session"
    assert cfg.overlay_clicks_required == 4
    assert cfg.desktop_message_seconds == 10
    assert cfg.overlay_strikes == 2


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(spike_threshold_dbfs=-11.5, cooldown_seconds=45)
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.spike_threshold_dbfs == -11.5
    assert loaded.cooldown_seconds == 45


def test_load_missing_file_returns_defaults(tmp_path):
    loaded = load_config(tmp_path / "does-not-exist.json")
    assert loaded == Config()


def test_load_ignores_unknown_keys_from_a_newer_version(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"cooldown_seconds": 60, "future_option": True}))
    loaded = load_config(path)
    assert loaded.cooldown_seconds == 60


def test_reset_deletes_the_config_and_its_backup(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(cooldown_seconds=45), path)
    save_config(Config(cooldown_seconds=60), path)  # second save creates the .bak
    assert path.exists()
    assert path.with_suffix(".json.bak").exists()

    reset_config(path)

    assert not path.exists()
    assert not path.with_suffix(".json.bak").exists()


def test_reset_leaves_a_fresh_load_at_defaults(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(device_name="Headset", cooldown_seconds=45), path)

    reset_config(path)

    assert load_config(path) == Config()


def test_reset_with_no_config_present_is_not_an_error(tmp_path):
    reset_config(tmp_path / "does-not-exist.json")  # must not raise


def test_reset_does_not_touch_other_files_in_the_same_directory(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(), path)
    sounds_dir = tmp_path / "sounds" / "first"
    sounds_dir.mkdir(parents=True)
    clip = sounds_dir / "a.wav"
    clip.write_bytes(b"not really audio")

    reset_config(path)

    assert clip.exists()


def test_load_fills_in_keys_missing_from_an_older_version(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"cooldown_seconds": 60}))
    loaded = load_config(path)
    assert loaded.spike_window_ms == 150


def test_corrupt_file_is_backed_up_and_defaults_returned(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ this is not json")
    loaded = load_config(path)
    assert loaded == Config()
    assert (tmp_path / "config.json.bad").read_text() == "{ this is not json"


def test_save_is_atomic_leaving_no_temp_file(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(), path)
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


def test_pin_hash_verifies_the_correct_pin():
    digest, salt = hash_pin("1234")
    assert verify_pin("1234", digest, salt) is True


def test_pin_hash_rejects_the_wrong_pin():
    digest, salt = hash_pin("1234")
    assert verify_pin("9999", digest, salt) is False


def test_pin_hash_uses_a_fresh_salt_each_time():
    _, salt_a = hash_pin("1234")
    _, salt_b = hash_pin("1234")
    assert salt_a != salt_b


def test_verify_pin_returns_false_when_no_pin_is_set():
    assert verify_pin("1234", "", "") is False


@pytest.mark.parametrize(
    "field, value",
    [
        ("threshold_mode", "telepathy"),
        ("session_reset_mode", "whenever"),
        ("cooldown_seconds", 0),
        ("spike_window_ms", -1),
        ("max_clip_seconds", 0),
        ("max_clip_seconds", -5),
        ("overlay_strikes", -1),
        ("overlay_strikes", 11),
    ],
)
def test_invalid_values_fall_back_to_defaults(tmp_path, field, value):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({field: value}))
    loaded = load_config(path)
    assert getattr(loaded, field) == getattr(Config(), field)


def test_saving_keeps_a_backup_of_the_previous_config(tmp_path):
    # The device pin, PIN hash and measured threshold cannot be regenerated.
    # A bad write used to lose all three with nothing to fall back on -- which
    # is exactly what happened once during development.
    path = tmp_path / "config.json"
    save_config(Config(spike_threshold_dbfs=-14.0, device_name="Headset"), path)
    save_config(Config(), path)

    restored = load_config(path.with_suffix(".json.bak"))
    assert restored.spike_threshold_dbfs == -14.0
    assert restored.device_name == "Headset"


def test_the_first_save_has_nothing_to_back_up(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(), path)
    assert not path.with_suffix(".json.bak").exists()


def test_schedule_defaults_are_off():
    cfg = Config()
    assert cfg.schedule_enabled is False
    assert cfg.schedule_off_from == "07:00"
    assert cfg.schedule_off_to == "22:00"
    assert cfg.clock_format == "24h"


def test_a_valid_schedule_round_trips(tmp_path):
    path = tmp_path / "config.json"
    save_config(
        Config(
            schedule_enabled=True,
            schedule_off_from="08:30",
            schedule_off_to="21:00",
            clock_format="12h",
        ),
        path,
    )
    loaded = load_config(path)
    assert loaded.schedule_enabled is True
    assert loaded.schedule_off_from == "08:30"
    assert loaded.schedule_off_to == "21:00"
    assert loaded.clock_format == "12h"


def test_a_time_typed_in_twelve_hour_form_is_stored_canonically(tmp_path):
    path = tmp_path / "config.json"
    save_config(
        Config(schedule_enabled=True, schedule_off_from="1pm", schedule_off_to="11 PM"),
        path,
    )
    loaded = load_config(path)
    assert loaded.schedule_off_from == "13:00"
    assert loaded.schedule_off_to == "23:00"
    assert loaded.schedule_enabled is True


def test_an_unparseable_time_disables_the_schedule_rather_than_guessing(tmp_path):
    path = tmp_path / "config.json"
    save_config(
        Config(schedule_enabled=True, schedule_off_from="whenever", schedule_off_to="22:00"),
        path,
    )
    loaded = load_config(path)
    # Detection must never be left switched off on a value nobody chose.
    assert loaded.schedule_enabled is False
    assert loaded.schedule_off_from == "07:00"


def test_equal_start_and_end_disables_the_schedule(tmp_path):
    path = tmp_path / "config.json"
    save_config(
        Config(schedule_enabled=True, schedule_off_from="09:00", schedule_off_to="9am"),
        path,
    )
    loaded = load_config(path)
    assert loaded.schedule_enabled is False


def test_an_unknown_clock_format_falls_back_to_twenty_four_hour(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(clock_format="swatch-beats"), path)
    assert load_config(path).clock_format == "24h"


def test_coerced_values_can_be_copied_back_onto_a_shared_config(tmp_path):
    """settingsui._save() must not strand the engine on uncoerced values.

    App hands one Config to both the engine and the settings window, so the
    coerced reload has to be written back onto that object rather than bound
    to a fresh one.
    """
    path = tmp_path / "config.json"
    shared = Config(
        cooldown_seconds=9999, schedule_enabled=True, schedule_off_from="banana"
    )
    save_config(shared, path)

    coerced = load_config(path)
    for field in fields(Config):
        setattr(shared, field.name, getattr(coerced, field.name))

    assert shared.cooldown_seconds == 10
    assert shared.schedule_off_from == "07:00"
    assert shared.schedule_enabled is False
