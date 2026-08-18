"""Turns a stream of frame RMS values into trigger events.

Pure logic: no audio library, no UI, no clock of its own. Callers supply the
frame values and the timestamps, which makes every rule here testable with
plain numbers.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass

from stfu.config import Config, FRAME_MS
from stfu.levels import dbfs_from_rms


class RollingRms:
    """RMS across the most recent `window_ms` of frames.

    Averages in the power domain, so a short loud burst inside a longer window
    is not flattened the way averaging decibels would flatten it.
    """

    def __init__(self, window_ms: int, frame_ms: int) -> None:
        self.window_frames = max(1, round(window_ms / frame_ms))
        self._squares: deque[float] = deque(maxlen=self.window_frames)

    def push(self, rms: float) -> float:
        self._squares.append(rms * rms)
        return self.value()

    def value(self) -> float:
        if not self._squares:
            return 0.0
        return math.sqrt(sum(self._squares) / len(self._squares))

    @property
    def is_full(self) -> bool:
        """True once the window holds a complete span of frames.

        The Detector refuses to act on a partial window. Without that, a single
        loud frame at startup or just after a reset would average to itself and
        trip the threshold -- precisely the transient the window exists to
        reject.
        """
        return len(self._squares) == self.window_frames

    def reset(self) -> None:
        self._squares.clear()


class Cooldown:
    """Suppresses triggers for a fixed period after one fires."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._last: float | None = None

    def allows(self, now: float) -> bool:
        if self._last is None:
            return True
        return now - self._last >= self.seconds

    def mark(self, now: float) -> None:
        self._last = now

    def remaining(self, now: float) -> float:
        if self._last is None:
            return 0.0
        return max(0.0, self.seconds - (now - self._last))

    def reset(self) -> None:
        self._last = None


class AdaptiveThreshold:
    """A threshold that tracks the room's baseline level.

    Guards against self-defeat: frames already above the threshold are excluded
    from the baseline, and the result is clamped between a floor and a ceiling.
    Without the exclusion a long loud stretch would raise the baseline until
    nothing could trigger; without the floor a silent room would drop the
    threshold onto ordinary speech.
    """

    #: Upper bound on retained samples. median() sorts a full copy, so an
    #: undecimated 10-minute window would sort 30,000 floats 50 times a second.
    MAX_BASELINE_SAMPLES = 1200

    def __init__(
        self,
        delta_db: float,
        min_threshold_dbfs: float,
        max_threshold_dbfs: float,
        baseline_minutes: int,
        frame_ms: int,
    ) -> None:
        self.delta_db = delta_db
        self.min_threshold_dbfs = min_threshold_dbfs
        self.max_threshold_dbfs = max_threshold_dbfs
        total_frames = max(1, round(baseline_minutes * 60_000 / frame_ms))
        # Keep one sample per _decimate frames. The baseline moves on a
        # ten-minute timescale, so sampling it 2x a second is ample, and it
        # keeps the median cheap enough to run in an audio frame budget.
        self._decimate = max(1, math.ceil(total_frames / self.MAX_BASELINE_SAMPLES))
        self._samples: deque[float] = deque(
            maxlen=max(1, round(total_frames / self._decimate))
        )
        self._since_sample = 0
        self._cached_raw: float | None = None

    def push(self, level_dbfs: float) -> float:
        """Feed one frame. Frames at or above the raw threshold are ignored.

        The first frame always seeds the window. With no samples there is no
        baseline to exclude against, and comparing against the clamped
        threshold instead would deadlock: in a room louder than the floor,
        nothing would ever be admitted and the baseline would stay empty.
        """
        if not self._samples:
            self._admit(level_dbfs)
        elif level_dbfs < self._raw_threshold():
            self._since_sample += 1
            if self._since_sample >= self._decimate:
                self._admit(level_dbfs)
        return self.threshold()

    def _admit(self, level_dbfs: float) -> None:
        self._samples.append(level_dbfs)
        self._since_sample = 0
        self._cached_raw = None

    def _raw_threshold(self) -> float:
        """baseline + delta, before the floor and ceiling are applied.

        Exclusion tests against this rather than against threshold(). The floor
        and ceiling are a policy clamp on the output — a statement about what
        trigger level is sane, not about which frames are room noise.

        Cached: only admitting a sample can change it, and admission happens
        once per _decimate frames at most.
        """
        if self._cached_raw is None:
            self._cached_raw = statistics.median(self._samples) + self.delta_db
        return self._cached_raw

    def threshold(self) -> float:
        if not self._samples:
            return self.min_threshold_dbfs
        return max(
            self.min_threshold_dbfs,
            min(self.max_threshold_dbfs, self._raw_threshold()),
        )

    def reset(self) -> None:
        self._samples.clear()
        self._since_sample = 0
        self._cached_raw = None


@dataclass(frozen=True)
class TriggerEvent:
    """One detected yell."""

    kind: str  # "spike" or "sustain"
    level_dbfs: float  # RMS across the rule's window, not a peak
    threshold_dbfs: float
    at: float  # monotonic seconds, as supplied by the caller


class Detector:
    """Frame RMS in, TriggerEvent out.

    Owns the two trigger rules, the three threshold modes, the cooldown gate,
    and the playback-suppression window. Deliberately has no clock: the caller
    supplies `now` on every push, which is what makes the timing testable.

    Config is snapshotted at construction: window lengths, cooldown, and the
    adaptive parameters are baked into the collaborators here. Callers must
    build a new Detector when settings change rather than mutating the Config
    in place, or the change will apply only partially.
    """

    def __init__(self, config: Config, frame_ms: int = FRAME_MS) -> None:
        self.config = config
        self._spike = RollingRms(config.spike_window_ms, frame_ms)
        self._sustain = RollingRms(config.sustain_window_ms, frame_ms)
        self._cooldown = Cooldown(config.cooldown_seconds)
        self._adaptive = AdaptiveThreshold(
            delta_db=config.adaptive_delta_db,
            min_threshold_dbfs=config.adaptive_min_threshold_dbfs,
            max_threshold_dbfs=config.adaptive_max_threshold_dbfs,
            baseline_minutes=config.adaptive_baseline_minutes,
            frame_ms=frame_ms,
        )
        self._suppressed_until = 0.0

    def current_threshold(self) -> float:
        """The spike threshold in force right now."""
        if self.config.threshold_mode == "adaptive":
            return self._adaptive.threshold()
        return self.config.spike_threshold_dbfs

    def suppress_until(self, when: float) -> None:
        """Ignore audio until `when`, and clear the rolling windows.

        Used while a sound bite is playing so the app cannot trigger on its own
        clip. The clearing is not optional: `push` returns before feeding the
        windows during suppression, so they freeze rather than track audio. The
        spike window is full and loud at the moment a trigger fires -- that is
        what made it fire -- so without clearing, the first frame after
        suppression lifts lands in a still-loud, still-full window and can fire
        again on pre-clip audio the moment the cooldown allows it.

        Only ever extends. A shorter `when` arriving while a longer suppression
        is active would otherwise expose the tail of the clip still playing, and
        a repeated call would re-clear the windows, which for the 3 s sustain
        window means it could never fill at all.
        """
        if when <= self._suppressed_until:
            return
        self._suppressed_until = when
        self._spike.reset()
        self._sustain.reset()

    def reset(self) -> None:
        self._spike.reset()
        self._sustain.reset()
        self._cooldown.reset()
        self._adaptive.reset()
        self._suppressed_until = 0.0

    def push(self, rms: float, now: float) -> TriggerEvent | None:
        """Feed one frame's RMS. `now` must be non-decreasing monotonic seconds
        — a backwards jump latches the cooldown shut until it catches up."""
        if now < self._suppressed_until:
            return None

        spike_dbfs = dbfs_from_rms(self._spike.push(rms))
        sustain_dbfs = dbfs_from_rms(self._sustain.push(rms))

        if self.config.threshold_mode == "adaptive":
            # Use push's return value; recomputing via current_threshold() here
            # would sort the baseline a second time in the same frame.
            spike_threshold = self._adaptive.push(spike_dbfs)
        else:
            spike_threshold = self.config.spike_threshold_dbfs
        sustain_threshold = self._sustain_threshold(spike_threshold)

        candidate = None
        if self._spike.is_full and spike_dbfs >= spike_threshold:
            candidate = TriggerEvent("spike", spike_dbfs, spike_threshold, now)
        elif (
            self.config.sustain_enabled
            and self._sustain.is_full
            and sustain_dbfs >= sustain_threshold
        ):
            candidate = TriggerEvent("sustain", sustain_dbfs, sustain_threshold, now)

        # One gate for both rules. They share a cooldown, so a spurious trigger
        # from either would swallow the next genuine one.
        if candidate is None or not self._cooldown.allows(now):
            return None
        self._cooldown.mark(now)
        return candidate

    def _sustain_threshold(self, spike_threshold: float) -> float:
        """The sustain threshold, shifted with the spike threshold in adaptive mode.

        The configured pair expresses a gap: sustain sits N dB below spike to
        catch quieter but longer noise. In adaptive mode the spike threshold
        moves with the room and a fixed sustain threshold does not. Since the
        adaptive floor (-20) sits above the sustain default (-24), that left
        sustain permanently more sensitive than spike could ever be — firing on
        room noise every cooldown period and starving the spike rule through
        the shared gate.
        """
        if self.config.threshold_mode != "adaptive":
            return self.config.sustain_threshold_dbfs
        gap = self.config.spike_threshold_dbfs - self.config.sustain_threshold_dbfs
        return spike_threshold - gap
