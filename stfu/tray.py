"""The tray icon and its menu.

pystray runs its own Win32 message loop in whatever thread calls
``icon.run()``. On Windows that loop is a per-thread thing (GetMessage /
PostMessage are scoped to the thread that created the window), so -- unlike
macOS -- it does not have to be the process's main thread. Only Tk is nailed
to one thread here.

That means every menu click lands on pystray's own thread, not Tk's. Anything
that touches Tk -- a window `action` opens, or the PIN prompt's dialog -- is
therefore dispatched through the UiBridge rather than called directly. This
project has shipped that bug twice already: a window built off the Tk thread
looks fine until the moment it doesn't.
"""

from __future__ import annotations

import io
import logging
import os
from typing import Callable

import pystray
from PIL import Image, ImageDraw

from stfu.config import Config, data_dir

log = logging.getLogger(__name__)

STATE_LISTENING = "listening"
STATE_PAUSED = "paused"
STATE_NO_MIC = "no_mic"

STATE_COLOURS = {
    STATE_LISTENING: "#2ecc71",
    STATE_PAUSED: "#f0a500",
    STATE_NO_MIC: "#888888",
}

STATE_TOOLTIPS = {
    STATE_LISTENING: "S.TFU - listening",
    STATE_PAUSED: "S.TFU - paused",
    STATE_NO_MIC: "S.TFU - microphone not found",
}

ICON_SIZE = 64
LOCK = "\U0001f512"  # a closed padlock, appended to PIN-gated menu items


def _icon_image(colour: str) -> Image.Image:
    """A plain coloured circle, drawn at runtime.

    Generated rather than shipped as a file: one less asset for PyInstaller to
    bundle, path-resolve when frozen, and potentially lose.
    """
    image = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = 6
    draw.ellipse(
        (margin, margin, ICON_SIZE - margin, ICON_SIZE - margin), fill=colour
    )
    return image


def preload_image_codecs() -> None:
    r"""Import every PIL codec now, on the main thread, before any thread runs.

    Pillow registers its plugins lazily: the ICO writer is not loaded until
    the first save() that needs it. pystray needs exactly that writer the
    moment it makes the tray icon visible -- and it does so from the tray
    thread. Frozen, that lazy import is a PyInstaller archive extraction, and
    running one on a background thread while the collector is walking the
    heap killed the process outright:

        Windows fatal exception: code 0x80000003
          Garbage-collecting
          File "pyimod01_archive.py", line 136 in extract
          File "PIL\Image.py", line 490 in init
          File "pystray\_win32.py", line 359 in _assert_icon_handle

    No traceback, no tray icon, no app -- and because it lands right after
    first-run setup, it reads as "setup finished and then nothing opened".

    Doing the work here costs a few milliseconds once and leaves the tray
    thread with no imports left to perform. The throwaway save is the point:
    Image.init() alone registers the plugins, but only an actual ICO write
    pulls in everything that write touches.
    """
    Image.init()
    try:
        _icon_image(STATE_COLOURS[STATE_LISTENING]).save(io.BytesIO(), "ICO")
    except Exception:
        # A codec that cannot round-trip here would fail on the tray thread
        # too, but there it takes the process with it. Log and carry on: a
        # missing tray icon is survivable, a dead app is not.
        log.exception("could not preload the tray icon codec")


class Tray:
    """Wraps ``pystray.Icon``. Runs on its own thread; every window a menu
    item opens is handed to the UiBridge so it is actually built on the Tk
    thread."""

    def __init__(
        self,
        config: Config,
        bridge,
        on_report: Callable[[], None],
        on_settings: Callable[[], None],
        on_recalibrate: Callable[[], None],
        on_meter: Callable[[], None],
        on_pause: Callable[[], None],
        on_exit: Callable[[], None],
        gate: Callable[[], bool],
    ) -> None:
        self.config = config
        self.bridge = bridge
        # Supplied by app.py rather than calling stfu.pinprompt directly, so
        # this module does not need to know about app.py's Tk root -- the
        # PIN dialog is a Toplevel of it now, not a standalone Tk() of its
        # own, and only app.py has that root to hand over.
        self._gate = gate
        self._state = STATE_LISTENING
        # Must happen before self.icon exists, and therefore before anything
        # can start the tray thread -- see preload_image_codecs.
        preload_image_codecs()

        self.icon = pystray.Icon(
            "stfu",
            icon=_icon_image(STATE_COLOURS[STATE_LISTENING]),
            title=STATE_TOOLTIPS[STATE_LISTENING],
            menu=pystray.Menu(
                pystray.MenuItem("Report", self._gated(on_report, gated=False)),
                # Read-only diagnostics (F5) -- no PIN, same as Report.
                pystray.MenuItem("Live meter", self._gated(on_meter, gated=False)),
                pystray.MenuItem("Open sounds folder", self._open_sounds_folder),
                pystray.MenuItem(
                    f"Settings {LOCK}", self._gated(on_settings, gated=True)
                ),
                pystray.MenuItem(
                    f"Recalibrate {LOCK}", self._gated(on_recalibrate, gated=True)
                ),
                pystray.MenuItem(
                    f"Pause 15 min {LOCK}", self._gated(on_pause, gated=True)
                ),
                pystray.MenuItem(f"Exit {LOCK}", self._gated(on_exit, gated=True)),
            ),
        )

    def run(self) -> None:
        """Block in pystray's own message loop until :meth:`stop` is called.

        Meant to be the target of a dedicated thread. On Windows this does not
        need to be the process main thread -- see the module docstring.
        """
        self.icon.run()

    def stop(self) -> None:
        self.icon.stop()

    def announce(self, title: str, message: str) -> None:
        """Raise a shell notification from the tray icon.

        S.TFU has no main window on purpose, and Windows files a brand-new
        tray icon behind the taskbar's overflow chevron rather than showing
        it. A first launch therefore looks exactly like a failed one: the
        splash plays, fades, and nothing visible is left. A notification is
        the one thing that surfaces without a window.

        Best effort by design -- notifications are a shell courtesy that a
        user, a group policy, or Focus Assist can switch off, and none of
        those is a reason to stop monitoring.
        """
        try:
            self.icon.notify(message, title)
        except Exception:
            log.debug("could not show the tray notification", exc_info=True)

    def set_state(self, state: str) -> None:
        """Update the icon colour and tooltip. Safe from any thread: pystray's
        Windows backend talks to the shell via the icon's own window handle,
        not the calling thread's message queue."""
        if state not in STATE_COLOURS:
            raise ValueError(f"unknown tray state: {state!r}")
        self._state = state
        self.icon.icon = _icon_image(STATE_COLOURS[state])
        self.icon.title = STATE_TOOLTIPS[state]

    @property
    def state(self) -> str:
        return self._state

    def _gated(self, action: Callable[[], None], gated: bool) -> Callable:
        """Build a pystray menu callback that runs `action` on the Tk thread,
        checking the PIN first when `gated` is set.

        The gate check and `action` run inside the *same* submitted callable
        so the PIN prompt's own `Tk()` and whatever window `action` opens both
        happen on the Tk thread, in the right order, without a second hop back
        to pystray's thread in between.
        """

        def callback(icon, item) -> None:
            def task() -> None:
                if gated and not self._gate():
                    return
                action()

            self.bridge.submit_async(task)

        return callback

    def _open_sounds_folder(self, icon, item) -> None:
        # Not gated, and it never touches Tk -- Explorer is its own process --
        # so this runs directly on pystray's thread.
        sounds_root = data_dir() / "sounds"
        for rung in ("first", "repeat"):
            (sounds_root / rung).mkdir(parents=True, exist_ok=True)
        os.startfile(sounds_root)  # noqa: S606 - opening a known local folder
