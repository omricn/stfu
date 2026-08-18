"""Bundled default sounds and images, and seeding them into user data.

The app ships with clips and pictures so it does something funny the moment it
is installed -- nobody should have to go and find sound effects before the app
will react at all.

They are copied into %LOCALAPPDATA%\\STFU during first-run setup rather than
played from inside the exe, so the operator can replace, add to, or delete them
exactly as if they had supplied them. Seeding happens once, at setup: running it
on every launch would resurrect files the operator deleted on purpose.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)

SEEDED_FOLDERS = ("sounds/first", "sounds/repeat", "images")


def assets_dir() -> Path:
    """Where the bundled assets live, frozen or not.

    PyInstaller unpacks a one-file build into a temp directory it exposes as
    sys._MEIPASS, with the package tree mirrored underneath it.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "stfu" / "assets"
    return Path(__file__).parent / "assets"


def seed_user_data(target: Path, source: Path | None = None) -> int:
    """Copy bundled defaults into the user's data folder. Returns the count.

    Never overwrites. A clip the operator has replaced stays replaced.
    """
    source = Path(source) if source is not None else assets_dir()
    copied = 0

    for folder in SEEDED_FOLDERS:
        destination_dir = Path(target) / folder
        destination_dir.mkdir(parents=True, exist_ok=True)

        source_dir = source / folder
        if not source_dir.is_dir():
            log.warning("bundled assets missing: %s", source_dir)
            continue

        for item in sorted(source_dir.iterdir()):
            # Dotfiles are repository plumbing -- a .gitkeep holding an
            # otherwise-empty folder in version control is not an asset, and
            # copying it into the user's data folder is just litter.
            if not item.is_file() or item.name.startswith("."):
                continue
            destination = destination_dir / item.name
            if destination.exists():
                continue
            shutil.copy2(item, destination)
            copied += 1

    return copied
