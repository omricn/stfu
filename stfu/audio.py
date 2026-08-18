"""Microphone capture.

The only module that touches audio hardware. Everything upstream consumes the
AudioSource protocol, so the detection pipeline is testable without a mic.

sounddevice does not expose Windows device instance IDs, so a device is pinned
by name plus host API name. That pair is stable across reboots and replugs for
a given headset, which is what the spec's "pinned device, no auto-switching"
requires.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Iterator, Protocol

import numpy as np

from stfu.config import FRAME_MS
from stfu.levels import rms_of_frame


def frame_samples_for_rate(sample_rate: float, frame_ms: int = FRAME_MS) -> int:
    """Sample count for one `frame_ms` frame at `sample_rate`.

    F6: the stream used to force samplerate=16000 no matter what the device's
    native rate was, so Windows resampled every buffer on the way in for a
    device that runs at 44100 or 48000 (the common case). Opening at the
    device's own default rate removes that resampling step, but the
    blocksize (in samples) has to scale with it to keep each frame at
    `frame_ms` -- the duration the detector's rolling windows assume one
    frame equals, regardless of what rate produced it.

    Rounded rather than truncated: a rate that does not divide frame_ms
    evenly (e.g. 11025 Hz) would otherwise drift the frame duration low by up
    to a whole sample's worth every frame. round() keeps it within half a
    sample of exactly `frame_ms`, and floors at 1 so a degenerate rate can
    never produce a zero-length block.
    """
    return max(1, round(sample_rate * frame_ms / 1000))


@dataclass(frozen=True)
class InputDevice:
    index: int
    name: str
    hostapi: str


class AudioSource(Protocol):
    """Yields one linear RMS value per frame."""

    @property
    def available(self) -> bool: ...

    def frames(self) -> Iterator[float]: ...


def list_input_devices() -> list[InputDevice]:
    """Every device with at least one input channel."""
    import sounddevice as sd

    hostapis = sd.query_hostapis()
    devices = []
    for index, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] > 0:
            devices.append(
                InputDevice(
                    index=index,
                    name=info["name"],
                    hostapi=hostapis[info["hostapi"]]["name"],
                )
            )
    return devices


_HOSTAPI_PREFERENCE = [
    "Windows WASAPI",
    "Windows DirectSound",
    "MME",
    "Windows WDM-KS",
]

# PortAudio enumerates every device once per host API, so one physical
# headset can appear three or four times. Anything starting with one of these
# is a host-API alias or a virtual endpoint, not a capture device someone
# would choose -- e.g. "Microsoft Sound Mapper - Input", "Primary Sound
# Capture Driver", "PC Speaker (...)".
_JUNK_NAME_PREFIXES = (
    "Microsoft Sound Mapper",
    "Primary Sound Capture Driver",
    "PC Speaker",
)

# Raw Windows driver strings PortAudio surfaces for some Bluetooth endpoints,
# e.g. "Input (@System32\\drivers\\bthhfenum.sys,#2;%1 Hands-Free%0;(...))".
# Not something a user could recognise as their headset.
_DRIVER_STRING_MARKERS = ("@System32\\", ";%1")

# MME truncates device names to 31 characters. Grouping strictly by full name
# would leave a truncated MME entry (e.g. "Microphone Array (Intel® Smart ")
# ungrouped with its untruncated WASAPI/DirectSound sibling, surviving as a
# spurious duplicate. Folding every name to this length before grouping fixes
# that; the (judged unlikely, and not present in any known device list here)
# cost is that two distinct devices whose names agree on the first 31
# characters would be merged into one entry.
_MME_TRUNCATION_LENGTH = 31


def _is_junk_device_name(name: str) -> bool:
    if name.startswith(_JUNK_NAME_PREFIXES):
        return True
    return any(marker in name for marker in _DRIVER_STRING_MARKERS)


def _hostapi_rank(hostapi: str) -> int:
    try:
        return _HOSTAPI_PREFERENCE.index(hostapi)
    except ValueError:
        return len(_HOSTAPI_PREFERENCE)


def _grouping_key(name: str) -> str:
    return name[:_MME_TRUNCATION_LENGTH]


def preferred_input_devices(devices: list[InputDevice]) -> list[InputDevice]:
    """Collapse PortAudio's one-entry-per-host-API enumeration into one entry
    per physical device, for display in the wizard.

    Junk entries (host-API aliases, non-capture endpoints, raw driver
    strings) are dropped outright. What remains is grouped by name --
    truncated to MME's 31-character limit so a truncated MME entry merges
    with its untruncated sibling rather than surviving as a duplicate -- and
    within each group the host API is preferred in the order WASAPI >
    DirectSound > MME > WDM-KS, since WASAPI is the modern shared-mode path
    and the lowest latency of the four.

    Groups are returned in the order their first surviving member was
    enumerated, so the list is stable between runs. The full, unfiltered list
    stays available via list_input_devices() and `stfu.cli devices`.
    """
    order: list[str] = []
    best: dict[str, InputDevice] = {}

    for device in devices:
        if _is_junk_device_name(device.name):
            continue
        key = _grouping_key(device.name)
        current = best.get(key)
        if current is None:
            order.append(key)
            best[key] = device
        elif _hostapi_rank(device.hostapi) < _hostapi_rank(current.hostapi):
            best[key] = device

    return [best[key] for key in order]


def find_device(
    name: str, hostapi: str, devices: list[InputDevice] | None = None
) -> InputDevice | None:
    """Resolve the pinned device. Exact name match required; the host API is a
    preference, not a requirement, so a driver stack change does not orphan the
    pin."""
    if not name:
        return None
    if devices is None:
        devices = list_input_devices()

    for device in devices:
        if device.name == name and device.hostapi == hostapi:
            return device
    for device in devices:
        if device.name == name:
            return device
    return None


class FakeSource:
    """Scripted source for tests. Yields the frame values it was constructed
    with, then stops."""

    def __init__(self, values: list[float], available: bool = True) -> None:
        self._values = values
        self._available = available

    @property
    def available(self) -> bool:
        return self._available

    def frames(self) -> Iterator[float]:
        yield from self._values


class MicSource:
    """Live capture from the pinned device.

    PortAudio calls back on its own thread; frames cross to the consumer through
    a bounded queue. The queue drops the oldest frame when full rather than
    blocking the callback, because blocking an audio callback causes glitches
    and, on WASAPI, stream death.
    """

    def __init__(self, device_name: str, device_hostapi: str, max_queue: int = 250):
        self.device_name = device_name
        self.device_hostapi = device_hostapi
        self._queue: queue.Queue[float] = queue.Queue(maxsize=max_queue)
        self._stream = None
        self._stop = threading.Event()
        # Set by open() to whatever the device's own default rate turned out
        # to be (F6) -- there is no fixed value any more, so nothing before
        # a successful open() can know it.
        self.samplerate: float | None = None

    @property
    def available(self) -> bool:
        return find_device(self.device_name, self.device_hostapi) is not None

    def _callback(self, indata: np.ndarray, frames, time_info, status) -> None:
        value = rms_of_frame(indata[:, 0])
        try:
            self._queue.put_nowait(value)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(value)
            except (queue.Empty, queue.Full):
                pass

    def open(self) -> bool:
        """Open the stream. Returns False if the pinned device is absent.

        Clears the stop flag so a source can be reopened after close(). The
        headset being unplugged and plugged back in is the normal case here,
        not an edge case; without this, a reopened source starts a stream but
        frames() exits immediately and yields nothing.

        Opens at the device's own default sample rate rather than forcing
        16 kHz (F6): loudness does not care about sample rate, and forcing
        one that is not the device's native rate makes Windows resample
        every buffer on the way in. The blocksize is derived from that rate
        so each frame is still ~20ms -- see frame_samples_for_rate -- which
        is the frame duration the detector's rolling windows are sized in.
        """
        import sounddevice as sd

        device = find_device(self.device_name, self.device_hostapi)
        if device is None:
            return False
        self._stop.clear()
        samplerate = float(sd.query_devices(device.index)["default_samplerate"])
        blocksize = frame_samples_for_rate(samplerate, FRAME_MS)
        self._stream = sd.InputStream(
            device=device.index,
            channels=1,
            samplerate=samplerate,
            blocksize=blocksize,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        self.samplerate = samplerate
        return True

    def close(self) -> None:
        self._stop.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def frames(self) -> Iterator[float]:
        """Block for frames until close() is called."""
        while not self._stop.is_set():
            try:
                yield self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
