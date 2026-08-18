"""The named actions the engine dispatches into.

The engine knows only names. Adding an action -- the planned USB indicator
light, for instance -- means writing one method and registering its name here,
with no change to detection, strikes, or the engine.
"""

from __future__ import annotations

import logging
from typing import Callable

from stfu.config import Config
from stfu.sounds import RUNG_FIRST, RUNG_REPEAT, SoundBite
from stfu.strikes import ACTION_DESKTOP_DROP, ACTION_OVERLAY
from stfu.winapi import WinApi

log = logging.getLogger(__name__)

ACTION_USB_LIGHT = "usb_light"


class ActionRegistry:
    """Maps an action name to what actually happens on screen.

    Both visible actions leave the game first. That is the spec's accepted
    trade-off: an exclusive-fullscreen DirectX game will not reliably let
    another window draw on top, so the only way to guarantee the message is seen
    is to drop out of the game before showing it.
    """

    def __init__(
        self,
        config: Config,
        winapi: WinApi,
        sound: SoundBite,
        overlay_factory: Callable[[], object],
        message_factory: Callable[[], object],
    ) -> None:
        self.config = config
        self.winapi = winapi
        self.sound = sound
        self._overlay_factory = overlay_factory
        self._message_factory = message_factory
        self._handlers = {
            ACTION_OVERLAY: self._overlay,
            ACTION_DESKTOP_DROP: self._desktop_drop,
            ACTION_USB_LIGHT: self._usb_light,
        }

    def fire(self, name: str, event) -> float | None:
        """Run an action. Returns the sound clip duration, or None.

        The engine uses that duration to suppress detection so the app cannot
        trigger on its own sound bite.
        """
        handler = self._handlers.get(name)
        if handler is None:
            log.warning("no handler registered for action %r", name)
            return None
        return handler(event)

    def _overlay(self, event) -> float | None:
        self.winapi.minimize_foreground()
        # Sound first: the overlay blocks until dismissed, so a clip started
        # after it would not play until the user had already closed the window.
        seconds = self.sound.play(RUNG_FIRST)
        self._overlay_factory().show()
        return seconds

    def _desktop_drop(self, event) -> float | None:
        self.winapi.show_desktop()
        seconds = self.sound.play(RUNG_REPEAT)
        self._message_factory().show()
        return seconds

    def _usb_light(self, event) -> float | None:
        """Stub for the planned USB indicator light.

        Registered so the wiring is proven, disabled until hardware is chosen.
        TODO: open the serial/HID device and set the colour from event.kind.
        """
        return None
