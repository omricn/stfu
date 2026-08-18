import threading

import pytest

from stfu.uibridge import UiBridge


def test_a_request_runs_when_pumped():
    bridge = UiBridge()
    result = []
    bridge.submit_async(lambda: result.append("ran"))
    bridge.pump_once()
    assert result == ["ran"]


def test_nothing_runs_before_a_pump():
    bridge = UiBridge()
    result = []
    bridge.submit_async(lambda: result.append("ran"))
    assert result == []


def test_pumping_an_empty_queue_is_harmless():
    UiBridge().pump_once()


def test_submit_blocks_until_pumped_and_returns_the_value():
    bridge = UiBridge()
    answers = []

    def worker():
        answers.append(bridge.submit(lambda: 42))

    thread = threading.Thread(target=worker)
    thread.start()
    # The worker is blocked until the "main thread" pumps.
    thread.join(timeout=0.2)
    assert thread.is_alive()
    assert answers == []

    bridge.pump_once()
    thread.join(timeout=2.0)
    assert answers == [42]


def test_an_exception_in_a_request_reaches_the_caller():
    bridge = UiBridge()
    errors = []

    def worker():
        try:
            bridge.submit(lambda: 1 / 0)
        except ZeroDivisionError as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    for _ in range(50):
        bridge.pump_once()
        if errors:
            break
    thread.join(timeout=2.0)
    assert len(errors) == 1


def test_an_exception_does_not_stop_later_requests():
    bridge = UiBridge()
    result = []
    bridge.submit_async(lambda: 1 / 0)
    bridge.submit_async(lambda: result.append("still here"))
    bridge.pump_once()
    bridge.pump_once()
    assert result == ["still here"]


def test_requests_run_in_order():
    bridge = UiBridge()
    order = []
    for i in range(5):
        bridge.submit_async(lambda i=i: order.append(i))
    for _ in range(5):
        bridge.pump_once()
    assert order == [0, 1, 2, 3, 4]


def test_pump_once_drains_only_one_request():
    bridge = UiBridge()
    order = []
    bridge.submit_async(lambda: order.append("a"))
    bridge.submit_async(lambda: order.append("b"))
    bridge.pump_once()
    assert order == ["a"]


def test_shutdown_releases_a_waiting_caller():
    bridge = UiBridge()
    errors = []

    def worker():
        try:
            bridge.submit(lambda: "never runs")
        except RuntimeError as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=0.2)
    assert thread.is_alive()

    bridge.shutdown()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert len(errors) == 1


def test_submitting_after_shutdown_raises_rather_than_hanging():
    bridge = UiBridge()
    bridge.shutdown()
    with pytest.raises(RuntimeError):
        bridge.submit(lambda: 1)


def test_a_request_returning_none_is_not_mistaken_for_a_shutdown():
    # Regression: shutdown used to be inferred from "no value and no error",
    # which a request legitimately returning None matches exactly. Actions
    # return None whenever no sound clip plays, so this is the normal path.
    bridge = UiBridge()
    results = []
    errors = []

    def worker():
        try:
            results.append(bridge.submit(lambda: None))
        except RuntimeError as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    assert bridge.pump_once(timeout=2.0) is True
    bridge.shutdown()
    thread.join(timeout=2.0)
    assert errors == []
    assert results == [None]


def test_a_keyboard_interrupt_also_reaches_the_pumping_thread():
    # Otherwise Ctrl+C inside a pumped callback is redirected to the capture
    # thread, leaving Tk's mainloop and the tray icon running.
    bridge = UiBridge()

    def boom():
        raise KeyboardInterrupt

    bridge.submit_async(boom)
    with pytest.raises(KeyboardInterrupt):
        bridge.pump_once()
