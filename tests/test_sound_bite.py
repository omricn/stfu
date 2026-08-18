import random

import pytest

from stfu.sounds import ClipLibrary, FakePlayer, SoundBite


def make(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"not really audio")


@pytest.fixture
def bite(tmp_path):
    (tmp_path / "first").mkdir(parents=True)
    library = ClipLibrary(tmp_path, rng=random.Random(0))
    return SoundBite(library, FakePlayer(duration=2.5), gain=1.0, max_seconds=15)


def test_playing_with_no_clips_returns_none(bite):
    assert bite.play("first") is None


def test_playing_with_no_clips_does_not_call_the_player(bite):
    bite.play("first")
    assert bite.player.played == []


def test_playing_returns_the_clip_duration(bite, tmp_path):
    make(tmp_path / "first", "a.wav")
    assert bite.play("first") == 2.5


def test_playing_passes_the_gain_and_limit_through(bite, tmp_path):
    make(tmp_path / "first", "a.wav")
    bite.play("first")
    assert bite.player.played[0][1] == 1.0
    assert bite.player.played[0][2] == 15


def test_a_player_failure_is_swallowed_and_returns_none(tmp_path):
    make(tmp_path / "first", "a.wav")
    library = ClipLibrary(tmp_path, rng=random.Random(0))
    bite = SoundBite(library, FakePlayer(raises=True), gain=1.0, max_seconds=15)
    # A corrupt clip must never take down the trigger path.
    assert bite.play("first") is None


def test_a_new_clip_stops_the_one_still_playing(bite, tmp_path):
    make(tmp_path / "first", "a.wav", "b.wav")
    bite.play("first")
    bite.play("first")
    assert bite.player.stops == 1  # stopped once, before the second play
