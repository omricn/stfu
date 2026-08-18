import random

import pytest

from stfu.sounds import SUPPORTED_SUFFIXES, ClipLibrary


@pytest.fixture
def library(tmp_path):
    (tmp_path / "first").mkdir()
    (tmp_path / "repeat").mkdir()
    return ClipLibrary(tmp_path, rng=random.Random(0))


def make(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"not really audio")


def test_no_clips_anywhere_picks_nothing(library):
    assert library.pick("first") is None


def test_picks_a_clip_from_the_rung_folder(library, tmp_path):
    make(tmp_path / "first", "a.wav")
    assert library.pick("first").name == "a.wav"


def test_falls_back_to_loose_clips_when_the_rung_is_empty(library, tmp_path):
    make(tmp_path, "shared.wav")
    assert library.pick("first").name == "shared.wav"


def test_the_rung_folder_wins_over_loose_clips(library, tmp_path):
    make(tmp_path, "shared.wav")
    make(tmp_path / "first", "specific.wav")
    assert library.pick("first").name == "specific.wav"


def test_the_two_rungs_are_independent(library, tmp_path):
    make(tmp_path / "first", "one.wav")
    make(tmp_path / "repeat", "two.wav")
    assert library.pick("first").name == "one.wav"
    assert library.pick("repeat").name == "two.wav"


def test_unsupported_files_are_ignored(library, tmp_path):
    make(tmp_path / "first", "readme.txt", "cover.jpg", "real.wav")
    assert library.pick("first").name == "real.wav"


def test_every_supported_suffix_is_accepted(library, tmp_path):
    make(tmp_path / "first", *[f"clip{s}" for s in SUPPORTED_SUFFIXES])
    assert len(library.clips_for("first")) == len(SUPPORTED_SUFFIXES)


def test_suffix_matching_is_case_insensitive(library, tmp_path):
    make(tmp_path / "first", "LOUD.WAV")
    assert library.pick("first").name == "LOUD.WAV"


def test_a_single_clip_repeats_happily(library, tmp_path):
    make(tmp_path / "first", "only.wav")
    assert [library.pick("first").name for _ in range(5)] == ["only.wav"] * 5


def test_never_plays_the_same_clip_twice_in_a_row(library, tmp_path):
    make(tmp_path / "first", "a.wav", "b.wav", "c.wav")
    picks = [library.pick("first").name for _ in range(40)]
    assert not any(x == y for x, y in zip(picks, picks[1:]))
    assert len(set(picks)) == 3  # and it does use all of them


def test_new_clips_are_seen_without_a_restart(library, tmp_path):
    make(tmp_path / "first", "a.wav")
    assert library.pick("first").name == "a.wav"
    make(tmp_path / "first", "b.wav")
    assert {library.pick("first").name for _ in range(20)} == {"a.wav", "b.wav"}


def test_a_missing_root_directory_is_not_fatal(tmp_path):
    library = ClipLibrary(tmp_path / "nope", rng=random.Random(0))
    assert library.pick("first") is None
    assert library.clips_for("first") == []
