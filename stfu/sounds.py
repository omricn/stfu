"""Sound bites: which clip to play, and how to play it.

Split deliberately. ClipLibrary is pure selection logic over a directory and is
fully unit-tested; Player touches the sound card and is replaced by FakePlayer
in tests.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = (".wav", ".mp3", ".ogg", ".flac")

RUNG_FIRST = "first"
RUNG_REPEAT = "repeat"


class ClipLibrary:
    """Picks a clip at random, never the same one twice in a row.

    The folder is rescanned on every pick so clips dropped in while the app is
    running take effect immediately -- the operator adds sound bites long after
    the app is deployed, and should not have to restart it.
    """

    def __init__(self, root: Path, rng: random.Random | None = None) -> None:
        self.root = Path(root)
        self._rng = rng or random.Random()
        self._last: dict[str, Path] = {}

    def clips_for(self, rung: str) -> list[Path]:
        """Clips for a rung, falling back to loose clips in the root."""
        return self._scan(self.root / rung) or self._scan(self.root)

    def _scan(self, folder: Path) -> list[Path]:
        if not folder.is_dir():
            return []
        return sorted(
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        )

    def pick(self, rung: str) -> Path | None:
        clips = self.clips_for(rung)
        if not clips:
            return None

        candidates = clips
        if len(clips) > 1:
            last = self._last.get(rung)
            # Falls back to the full list if excluding `last` empties it, which
            # cannot happen with two or more clips but keeps the choice total.
            candidates = [c for c in clips if c != last] or clips

        chosen = self._rng.choice(candidates)
        self._last[rung] = chosen
        return chosen


class Player(Protocol):
    def play(self, path: Path, gain: float, max_seconds: float) -> float: ...

    def stop(self) -> None: ...


class MiniaudioPlayer:
    """Decodes with miniaudio, plays through sounddevice. Non-blocking.

    Both imports are lazy so importing stfu.sounds does not initialise
    PortAudio -- the same discipline stfu.audio uses.
    """

    def play(self, path: Path, gain: float, max_seconds: float) -> float:
        import miniaudio
        import numpy as np
        import sounddevice as sd

        decoded = miniaudio.decode_file(
            str(path), output_format=miniaudio.SampleFormat.FLOAT32
        )
        data = np.asarray(decoded.samples, dtype=np.float32)
        if decoded.nchannels > 1:
            data = data.reshape(-1, decoded.nchannels)

        limit = int(max_seconds * decoded.sample_rate)
        data = data[:limit]
        # Clip after applying gain: a gain above 1.0 on an already-loud clip
        # would otherwise wrap around into noise rather than simply being loud.
        data = np.clip(data * gain, -1.0, 1.0)

        sd.play(data, decoded.sample_rate)
        return len(data) / decoded.sample_rate

    def stop(self) -> None:
        import sounddevice as sd

        sd.stop()


class FakePlayer:
    """Records what it was asked to play. Part of the module's contract."""

    def __init__(self, duration: float = 1.0, raises: bool = False) -> None:
        self.played: list[tuple[Path, float, float]] = []
        self.stops = 0
        self._duration = duration
        self._raises = raises

    def play(self, path: Path, gain: float, max_seconds: float) -> float:
        self.played.append((path, gain, max_seconds))
        if self._raises:
            raise RuntimeError("decode failed")
        return self._duration

    def stop(self) -> None:
        self.stops += 1


class SoundBite:
    """A clip library joined to a player. What actions.py holds."""

    def __init__(
        self,
        library: ClipLibrary,
        player: Player,
        gain: float,
        max_seconds: float,
    ) -> None:
        self.library = library
        self.player = player
        self.gain = gain
        self.max_seconds = max_seconds
        self._playing = False

    def play(self, rung: str) -> float | None:
        """Play a random clip for this rung. Returns its duration, or None.

        Returning None on any failure matters: the engine reads this value to
        decide how long to suppress detection, and a missing or corrupt clip
        must not suppress anything.
        """
        clip = self.library.pick(rung)
        if clip is None:
            return None

        if self._playing:
            # Cut off whatever is still going rather than overlapping.
            self.player.stop()

        try:
            duration = self.player.play(clip, self.gain, self.max_seconds)
        except Exception:
            log.exception("could not play %s", clip)
            self._playing = False
            return None

        self._playing = True
        return duration
