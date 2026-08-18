"""The tray icon and its menu.

pystray runs its own Win32 message loop in whatever thread calls
``icon.run()``. On Windows that loop is a per-thread thing (GetMessage /
PostMessage are scoped to the thread that created the window), so -- unlike
macOS -- it does not have to be the process's main thread. Only Tk is nailed
to one thread here.

That means every menu click lands on pystray's own thread, not Tk's. Anything
that touches Tk -- a window `action` opens, or the PIN prompt's own `Tk()` --
is therefore dispatched through the UiBridge rather than called directly. This
project has shipped that bug twice already: a window built off the Tk thread
looks fine until the moment it doesn't.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

import pystray
from PIL import Image, ImageDraw

from stfu import pinprompt
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
        on_pause: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self.config = config
        self.bridge = bridge
        self._state = STATE_LISTENING

        self.icon = pystray.Icon(
            "stfu",
            icon=_icon_image(STATE_COLOURS[STATE_LISTENING]),
            title=STATE_TOOLTIPS[STATE_LISTENING],
            menu=pystray.Menu(
                pystray.MenuItem("Report", self._gated(on_report, gated=False)),
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
                if gated and not pinprompt.gate(self.config):
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
