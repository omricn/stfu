"""Thin ctypes wrappers over the Win32 calls the actions need.

Isolated so everything above can be tested against FakeWinApi. Nothing here
makes a decision -- it only performs the call. That is what keeps actions.py
testable without a desktop.
"""

from __future__ import annotations

import ctypes
import logging
from typing import Protocol

log = logging.getLogger(__name__)

SW_MINIMIZE = 6
VK_LWIN = 0x5B
VK_D = 0x44
KEYEVENTF_KEYUP = 0x0002


class WinApi(Protocol):
    def minimize_foreground(self) -> bool: ...

    def show_desktop(self) -> None: ...


class RealWinApi:
    """The live implementation. Never exercised by automated tests."""

    def minimize_foreground(self) -> bool:
        """Minimise whatever window currently has focus.

        Returns False when there is no foreground window, which happens on a
        locked or freshly booted desktop. Callers treat that as "nothing to
        minimise" rather than an error.
        """
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            log.warning("no foreground window to minimise")
            return False
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        return True

    def show_desktop(self) -> None:
        """Send Win+D.

        Synthesised as four key events rather than via the shell's
        ToggleDesktop, which is a toggle: calling it twice restores the windows,
        and we can never be sure of the current state.
        """
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        user32.keybd_event(VK_D, 0, 0, 0)
        user32.keybd_event(VK_D, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)


class FakeWinApi:
    """Records calls instead of making them. Part of the module's contract."""

    def __init__(self, minimize_succeeds: bool = True) -> None:
        self.calls: list[str] = []
        self._minimize_succeeds = minimize_succeeds

    def minimize_foreground(self) -> bool:
        self.calls.append("minimize_foreground")
        return self._minimize_succeeds

    def show_desktop(self) -> None:
        self.calls.append("show_desktop")
