import random

import pytest

from stfu.images import SUPPORTED_SUFFIXES, ImageLibrary


@pytest.fixture
def library(tmp_path):
    return ImageLibrary(tmp_path, rng=random.Random(0))


def make(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"not really a picture")


def test_an_empty_folder_picks_nothing(library):
    assert library.pick() is None


def test_a_missing_folder_is_not_fatal(tmp_path):
    assert ImageLibrary(tmp_path / "nope").pick() is None


def test_it_picks_a_picture(library, tmp_path):
    make(tmp_path, "a.png")
    assert library.pick().name == "a.png"


def test_unsupported_files_are_ignored(library, tmp_path):
    make(tmp_path, "notes.txt", "clip.mp3", "real.png")
    assert library.pick().name == "real.png"


def test_every_supported_suffix_is_accepted(library, tmp_path):
    make(tmp_path, *[f"pic{suffix}" for suffix in SUPPORTED_SUFFIXES])
    assert len(library.available()) == len(SUPPORTED_SUFFIXES)


def test_suffix_matching_is_case_insensitive(library, tmp_path):
    make(tmp_path, "SHHH.PNG")
    assert library.pick().name == "SHHH.PNG"


def test_a_single_picture_repeats_happily(library, tmp_path):
    make(tmp_path, "only.png")
    assert [library.pick().name for _ in range(5)] == ["only.png"] * 5


def test_never_shows_the_same_picture_twice_in_a_row(library, tmp_path):
    make(tmp_path, "a.png", "b.png", "c.png")
    picks = [library.pick().name for _ in range(40)]
    assert not any(x == y for x, y in zip(picks, picks[1:]))
    assert len(set(picks)) == 3


def test_new_pictures_are_seen_without_a_restart(library, tmp_path):
    make(tmp_path, "a.png")
    assert library.pick().name == "a.png"
    make(tmp_path, "b.png")
    assert {library.pick().name for _ in range(20)} == {"a.png", "b.png"}


def test_a_directory_named_like_a_picture_is_ignored(library, tmp_path):
    (tmp_path / "trap.png").mkdir()
    make(tmp_path, "real.png")
    assert library.pick().name == "real.png"
