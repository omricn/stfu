"""One app at a time.

Autostart plus a manual launch would otherwise put two processes on one
microphone, doubling every trigger and corrupting the strike ladder.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

log = logging.getLogger(__name__)

MUTEX_NAME = "Local\\STFU_SingleInstance"
ERROR_ALREADY_EXISTS = 183


class Lock(Protocol):
    def take(self, name: str) -> bool: ...

    def drop(self, name: str) -> None: ...


class MutexLock:
    """A named Win32 mutex. Never exercised by automated tests."""

    def __init__(self) -> None:
        self._handles: dict[str, int] = {}

    def take(self, name: str) -> bool:
        import ctypes

        handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            ctypes.windll.kernel32.CloseHandle(handle)
            return False
        self._handles[name] = handle
        return True

    def drop(self, name: str) -> None:
        import ctypes

        handle = self._handles.pop(name, None)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)


class FakeLock:
    """In-memory lock shared between SingleInstance objects in a test."""

    def __init__(self) -> None:
        self.held: set[str] = set()

    def take(self, name: str) -> bool:
        if name in self.held:
            return False
        self.held.add(name)
        return True

    def drop(self, name: str) -> None:
        self.held.discard(name)


class SingleInstance:
    def __init__(self, lock: Lock | None = None, name: str = MUTEX_NAME) -> None:
        self._lock = lock or MutexLock()
        self._name = name
        self._acquired = False

    def acquire(
        self,
        retry_seconds: float = 0.0,
        poll_interval: float = 0.2,
        *,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> bool:
        """Try to take the lock, retrying for up to `retry_seconds` if it is
        currently held rather than giving up on the very first check.

        Two legitimate races land here. "Start over" (see app.py) spawns a
        replacement process before this one has released the mutex, so the
        new process's first attempt is expected to fail; and a plain manual
        relaunch right after closing the app can hit the same window, since
        this process's own teardown (joining the capture and tray threads,
        each with its own timeout) can take a few seconds after the mutex's
        owning handle is asked to close. Both used to mean "another instance
        is already running" and a silent exit, even though nothing else was
        actually still running by the time a user tried again by hand.

        `sleep`/`now` are injectable so tests can drive the retry loop
        without a real wall-clock wait (see tests/test_instance.py).
        """
        deadline = now() + retry_seconds
        while True:
            self._acquired = self._lock.take(self._name)
            if self._acquired or now() >= deadline:
                return self._acquired
            sleep(poll_interval)

    def release(self) -> None:
        if self._acquired:
            self._lock.drop(self._name)
            self._acquired = False

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *_exc) -> None:
        self.release()
