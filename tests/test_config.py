import json

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
