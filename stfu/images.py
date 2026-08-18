"""Which picture to show with a popup.

Mirrors ClipLibrary deliberately -- same rescan-every-pick behaviour, same
no-repeat rule -- but with a single pool rather than per-rung folders, because
a picture is not tied to which rung of the ladder fired.
"""

from __future__ import annotations

import random
from pathlib import Path

SUPPORTED_SUFFIXES = (".png", ".gif", ".jpg", ".jpeg")


class ImageLibrary:
    """Picks a picture at random, never the same one twice in a row.

    Rescanned on every pick so pictures dropped in while the app is running are
    used without a restart.
    """

    def __init__(self, root: Path, rng: random.Random | None = None) -> None:
        self.root = Path(root)
        self._rng = rng or random.Random()
        self._last: Path | None = None

    def available(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(
            path
            for path in self.root.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        )

    def pick(self) -> Path | None:
        pictures = self.available()
        if not pictures:
            return None

        candidates = pictures
        if len(pictures) > 1:
            candidates = [p for p in pictures if p != self._last] or pictures

        chosen = self._rng.choice(candidates)
        self._last = chosen
        return chosen
