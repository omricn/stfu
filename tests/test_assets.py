from stfu.assets import SEEDED_FOLDERS, assets_dir, seed_user_data


def test_the_bundled_assets_exist():
    root = assets_dir()
    assert root.is_dir()
    for folder in SEEDED_FOLDERS:
        assert (root / folder).is_dir(), folder


def test_the_bundle_contains_clips_for_both_rungs():
    root = assets_dir()
    assert list((root / "sounds/first").glob("*.mp3"))
    assert list((root / "sounds/repeat").glob("*.mp3"))


def test_the_bundle_ships_no_images():
    # Sound effects ship; pictures do not. The folder exists so it is
    # discoverable, and the operator drops their own pictures in.
    assert (assets_dir() / "images").is_dir()
    assert list((assets_dir() / "images").glob("*.png")) == []


def test_seeding_an_empty_target_copies_everything(tmp_path):
    copied = seed_user_data(tmp_path)
    assert copied == 7
    assert len(list((tmp_path / "sounds/first").iterdir())) == 4
    assert len(list((tmp_path / "sounds/repeat").iterdir())) == 3
    assert len(list((tmp_path / "images").iterdir())) == 0


def test_seeding_creates_the_folders(tmp_path):
    seed_user_data(tmp_path)
    for folder in SEEDED_FOLDERS:
        assert (tmp_path / folder).is_dir()


def test_seeding_twice_copies_nothing_the_second_time(tmp_path):
    seed_user_data(tmp_path)
    assert seed_user_data(tmp_path) == 0


def test_seeding_never_overwrites_an_existing_file(tmp_path):
    target = tmp_path / "images" / "shhh1.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"the operator's own picture")
    seed_user_data(tmp_path)
    assert target.read_bytes() == b"the operator's own picture"


def test_a_missing_source_folder_is_not_fatal(tmp_path):
    assert seed_user_data(tmp_path, source=tmp_path / "nowhere") == 0


def test_seeding_still_creates_folders_when_the_source_is_missing(tmp_path):
    seed_user_data(tmp_path, source=tmp_path / "nowhere")
    assert (tmp_path / "images").is_dir()


def test_seeding_ignores_repository_dotfiles(tmp_path):
    # The bundled images folder is held in git by a .gitkeep. That is plumbing,
    # not an asset, and must not end up in the user's data folder.
    seed_user_data(tmp_path)
    assert not list((tmp_path / "images").glob(".*"))
