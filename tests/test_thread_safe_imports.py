r"""Lazy imports must happen on the main thread, before any thread starts.

The app died immediately after first-run setup with no traceback at all:

    2026-08-19 12:18:02,857 INFO  stfu.app: entering the main event loop
    Windows fatal exception: code 0x80000003
      Garbage-collecting
      File "pyimod01_archive.py", line 136 in extract
      File "PIL\Image.py", line 490 in init
      File "pystray\_win32.py", line 359 in _assert_icon_handle
      File "threading.py", line 1012 in run

Pillow defers its ICO writer until the first save(); pystray needs it the
moment it shows the tray icon, from the tray thread. Frozen, that lazy
import unpacks a module from the PyInstaller archive -- and doing that on a
background thread while the collector ran took the whole process down.
`sounddevice` is the same shape: imported inside audio.py's functions, first
called from the capture thread.

So both are imported up front now, where a failure is an ordinary exception.
"""

import ast
import io
from pathlib import Path

import pytest
from PIL import Image

from stfu.audio import preload
from stfu.tray import STATE_COLOURS, STATE_LISTENING, _icon_image, preload_image_codecs

APP = Path(__file__).parent.parent / "stfu" / "app.py"


def run_body() -> ast.FunctionDef:
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    app = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "App"
    )
    return next(n for n in app.body if isinstance(n, ast.FunctionDef) and n.name == "run")


def first_thread_line() -> int:
    """The line where App.run() first mentions Thread."""
    return min(
        node.lineno
        for node in ast.walk(run_body())
        if isinstance(node, ast.Attribute) and node.attr == "Thread"
    )


@pytest.mark.parametrize("call", ["preload", "preload_image_codecs"])
def test_the_preloads_run_before_any_thread_is_created(call):
    calls = [
        node
        for node in ast.walk(run_body())
        if isinstance(node, ast.Call)
        and (
            getattr(node.func, "id", None) == call
            or getattr(node.func, "attr", None) == call
        )
    ]
    assert calls, f"App.run() never calls {call}()"
    assert min(c.lineno for c in calls) < first_thread_line(), (
        f"{call}() runs after a thread has already been started -- the "
        f"import it exists to force can still land on that thread"
    )


def test_preloading_the_codecs_makes_an_ico_write_import_free():
    preload_image_codecs()
    # Image.init() sets this once every plugin is registered. If it is still
    # unset, the tray thread's save() would do the importing itself.
    assert Image._initialized >= 2


def test_the_icon_actually_round_trips_to_ico():
    # The format pystray asks for. A codec that cannot write it here would
    # fail on the tray thread instead, where it is fatal.
    buffer = io.BytesIO()
    _icon_image(STATE_COLOURS[STATE_LISTENING]).save(buffer, "ICO")
    assert buffer.getvalue()[:4] == b"\x00\x00\x01\x00"  # ICO magic


def test_preloading_the_codecs_twice_is_harmless():
    # It is called from Tray.__init__ and again from App.run().
    preload_image_codecs()
    preload_image_codecs()


def test_audio_preload_imports_portaudio():
    preload()
    import sys

    assert "sounddevice" in sys.modules


def test_the_playback_stack_is_preloaded_too():
    """play() is reached from the capture thread on the first yell.

    miniaudio, numpy and sounddevice were imported inside play() itself, so
    the first strike of a session would have unpacked three modules from the
    archive on a background thread.
    """
    import sys

    from stfu.sounds import preload as preload_playback

    preload_playback()
    for module in ("miniaudio", "numpy", "sounddevice"):
        assert module in sys.modules


def test_app_run_preloads_the_playback_stack_before_any_thread():
    calls = [
        node.lineno
        for node in ast.walk(run_body())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "preload"
        and getattr(node.func.value, "id", None) == "sounds"
    ]
    assert calls, "App.run() never calls sounds.preload()"
    assert min(calls) < first_thread_line()
