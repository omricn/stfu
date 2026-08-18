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

from stfu.config import FRAME_MS, SAMPLE_RATE
from stfu.levels import rms_of_frame

FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320 samples at 16 kHz / 20 ms


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
        """
        import sounddevice as sd

        device = find_device(self.device_name, self.device_hostapi)
        if device is None:
            return False
        self._stop.clear()
        self._stream = sd.InputStream(
            device=device.index,
            channels=1,
            samplerate=SAMPLE_RATE,
            blocksize=FRAME_SAMPLES,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
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
