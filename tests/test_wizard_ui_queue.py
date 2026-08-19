"""Regression test: the calibrate step's Start button did nothing.

`_ui` marshalled cross-thread updates with `root.after()`. Tk's after() calls
createcommand, which raises "RuntimeError: main thread is not in main loop"
off the main thread -- so the helper written to make cross-thread updates safe
killed the calibration thread on its first call. With no handler around the
thread body the traceback went to stderr, which a windowed exe does not have,
so the button appeared inert.

Queue the work instead and let the main thread drain it, as uibridge.py does
for the rest of the app.
"""

import threading

from stfu.config import Config
from stfu.firstrunui import FirstRunWizard, _guarded


def wizard() -> FirstRunWizard:
    """A wizard with no Tk root -- these tests exercise the queue, not widgets."""
    return FirstRunWizard(Config())


def test_queueing_from_a_thread_does_not_raise():
    w = wizard()
    errors = []

    def worker():
        try:
            w._ui(w._render_token, lambda: None)
        except BaseException as exc:  # noqa: BLE001 - the point of the test
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=2.0)
    assert errors == []


def test_queued_work_is_not_run_until_it_is_drained():
    w = wizard()
    ran = []
    w._ui(w._render_token, lambda: ran.append(1))
    assert ran == []


def test_a_queued_callable_carries_its_step_token():
    w = wizard()
    w._ui(w._render_token, lambda: None)
    token, _fn = w._ui_queue.get_nowait()
    assert token == w._render_token


def test_work_from_a_replaced_step_is_dropped():
    # _render bumps the token; anything queued against the old one belongs to
    # widgets that have since been destroyed.
    w = wizard()
    stale = w._render_token
    w._ui(stale, lambda: None)
    w._render_token += 1
    token, _fn = w._ui_queue.get_nowait()
    assert token != w._render_token


def test_the_thread_guard_swallows_and_logs_a_crash():
    def boom():
        raise RuntimeError("main thread is not in main loop")

    _guarded(boom)()  # must not propagate


def test_the_thread_guard_passes_success_through():
    ran = []
    _guarded(lambda: ran.append(1))()
    assert ran == [1]
