"""Runs UI work on the main thread on behalf of other threads.

Tk is not thread-safe and its windows must live on one thread, but the audio
capture thread is what discovers a yell -- and it has to BLOCK until the
overlay is dismissed, because the engine uses the return value to decide how
long to suppress detection.

submit() enqueues the work, waits, and returns what it produced. The main
thread calls pump_once() repeatedly (via Tk's after()) to run it.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)


class _Request:
    __slots__ = ("fn", "done", "value", "error", "wait", "ran")

    def __init__(self, fn: Callable[[], Any], wait: bool) -> None:
        self.fn = fn
        self.wait = wait
        self.done = threading.Event()
        self.value: Any = None
        self.error: BaseException | None = None
        self.ran = False


class UiBridge:
    def __init__(self) -> None:
        self._queue: queue.Queue[_Request] = queue.Queue()
        self._closed = threading.Event()
        self._pending: list[_Request] = []
        self._lock = threading.Lock()

    def submit(self, fn: Callable[[], Any]) -> Any:
        """Run `fn` on the pumping thread and return its result.

        Blocks the calling thread. Re-raises whatever `fn` raised, so a caller
        sees a failure the same way it would from a direct call.
        """
        if self._closed.is_set():
            raise RuntimeError("UI bridge is shut down")

        request = _Request(fn, wait=True)
        with self._lock:
            self._pending.append(request)
        self._queue.put(request)
        request.done.wait()

        # An explicit flag, not an inference. A request that legitimately ran
        # and returned None is otherwise indistinguishable from one that never
        # ran at all -- and returning None is the common case, not a corner.
        if not request.ran:
            raise RuntimeError("UI bridge shut down before the request ran")
        if request.error is not None:
            raise request.error
        return request.value

    def submit_async(self, fn: Callable[[], Any]) -> None:
        """Queue `fn` and return immediately. Failures are logged, not raised."""
        if self._closed.is_set():
            return
        self._queue.put(_Request(fn, wait=False))

    def pump_once(self, timeout: float = 0.0) -> bool:
        """Run at most one queued request. Returns whether one was run.

        Called from the main thread, normally on a Tk after() timer.
        """
        try:
            request = self._queue.get(timeout=timeout) if timeout else self._queue.get_nowait()
        except queue.Empty:
            return False

        try:
            request.value = request.fn()
        except BaseException as exc:  # noqa: BLE001 - forwarded to the caller
            request.error = exc
            if not request.wait:
                log.exception("UI request failed")
        finally:
            request.ran = True
            request.done.set()
            with self._lock:
                if request in self._pending:
                    self._pending.remove(request)

        # Forwarded to the waiting caller above, but a process-level interrupt
        # must also take down the thread that owns Tk's mainloop -- otherwise
        # Ctrl+C landing inside a pumped callback is redirected onto the capture
        # thread and the app keeps running.
        if isinstance(request.error, (KeyboardInterrupt, SystemExit)):
            raise request.error
        return True

    def shutdown(self) -> None:
        """Stop accepting work and release anyone still blocked in submit()."""
        self._closed.set()
        with self._lock:
            pending, self._pending = self._pending, []
        for request in pending:
            request.done.set()
