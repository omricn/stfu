"""A windowed exe has no stderr, so every death must be logged.

After first-run setup the app opened its microphone, wrote its last routine
INFO line, and disappeared. Nothing in app.log distinguished a clean exit
from an unhandled exception from a native fault inside PortAudio, because
Python's default hooks all write to a stderr that does not exist. Hours went
into inferring from timestamps what one log line would have stated outright.

These are mechanical guards: they assert the hooks are installed and the
markers exist, not what they print.
"""

import ast
import logging
import sys
import threading
from pathlib import Path

import pytest

APP = Path(__file__).parent.parent / "stfu" / "app.py"
SOURCE = APP.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def assigned_names() -> set[str]:
    """Every dotted target assigned anywhere in app.py, e.g. sys.excepthook."""
    found = set()
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                found.add(f"{target.value.id}.{target.attr}")
    return found


@pytest.mark.parametrize("hook", ["sys.excepthook", "threading.excepthook"])
def test_the_uncaught_exception_hooks_are_installed(hook):
    assert hook in assigned_names(), (
        f"{hook} is not set, so an unhandled exception in a windowed exe goes "
        f"to a stderr that does not exist and the app vanishes silently"
    )


def test_native_faults_are_captured():
    assert "faulthandler.enable" in SOURCE, (
        "without faulthandler a segfault inside PortAudio or Tk leaves no "
        "trace at all -- the log simply stops mid-session"
    )


def test_a_clean_exit_says_so():
    # The distinguishing marker: only an orderly shutdown reaches atexit, so
    # its absence is what tells you the process was killed or faulted.
    assert "atexit.register" in SOURCE
    assert "exiting normally" in SOURCE


def test_the_event_loop_is_marked_on_both_sides():
    # "Started but never returned" and "returned immediately" are the two
    # failure modes chased after setup; they look identical without these.
    assert "entering the main event loop" in SOURCE
    assert "the main event loop returned" in SOURCE


def test_the_setup_save_reports_what_landed_on_disk():
    # save_config() succeeding and the file existing are different claims.
    assert "_save_setup_result" in SOURCE
    assert "saved setup to %s" in SOURCE


def test_the_hooks_survive_a_handler_without_a_usable_stream():
    """_catch_silent_deaths must not raise on a handler faulthandler cannot use.

    It runs during logging setup, before anything else -- if it throws, the
    app dies before it can report why.
    """
    from stfu.app import _catch_silent_deaths

    original_sys, original_thread = sys.excepthook, threading.excepthook
    try:
        _catch_silent_deaths(logging.NullHandler())
        assert sys.excepthook is not original_sys
        assert threading.excepthook is not original_thread
    finally:
        sys.excepthook, threading.excepthook = original_sys, original_thread


def test_a_successful_first_launch_tells_the_user_it_is_running():
    """The app has no main window, so a healthy start is invisible.

    Setup completed, the splash played, and the report was that the app "did
    not open" -- it had opened and was listening. Windows files a brand-new
    tray icon behind the overflow chevron, so there was nothing on screen to
    say so.
    """
    assert "just_set_up" in SOURCE
    assert "_announce_running" in SOURCE


def test_the_announcement_never_stops_the_app():
    """Notifications are a shell courtesy -- Focus Assist, policy, or a user
    setting can refuse them, and none of that is a reason to stop monitoring.
    """
    from unittest.mock import MagicMock

    from stfu.tray import Tray

    tray = Tray.__new__(Tray)
    tray.icon = MagicMock()
    tray.icon.notify.side_effect = RuntimeError("notifications are disabled")
    tray.announce("title", "message")  # must not propagate
