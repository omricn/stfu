"""The app's own icon: the S.TFU waveform mark, drawn with Pillow (F7, then
rebranded -- see docs/BRAND.md).

Generated rather than checked into the repo as a binary asset, for the same
reason tray.py draws its coloured circles at runtime and stfu.spec built its
placeholder .ico at build time: one less asset to keep in sync, path-resolve
when frozen, or lose track of. This module is the single source of the app's
*icon* artwork -- stfu.spec renders it into the .ico applied to the exe
itself, and every Tk window in this app applies it at runtime via iconphoto
so title bars and the taskbar show it too. The actual drawing lives in
`brand.py`, which this module defers to, so the icon, the static mark shown
on screens, and the drawn splash fallback are all the same artwork rather
than three that can drift apart.

This used to be a different, separate piece of artwork (a speaker with a
mute slash) from the tray icon (tray.py): a plain coloured circle there
carries live app state (green listening / amber paused / grey no mic) that a
single static app icon can't express, so the tray still keeps its own
circles rather than reusing this one -- only the *icon*, not the tray, was
rebranded to the waveform mark.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PIL import Image

from stfu import brand

if TYPE_CHECKING:
    import tkinter as tk

log = logging.getLogger(__name__)

ICON_SIZES = (16, 32, 48, 64, 128, 256)


def draw_icon(size: int) -> Image.Image:
    """Render the app icon at `size` x `size` pixels, RGBA with a transparent
    background: the resting (non-animated) S.TFU waveform mark."""
    return brand.draw_mark(size)


def icon_images(sizes: tuple[int, ...] = ICON_SIZES) -> list[Image.Image]:
    """The icon rendered at every size PyInstaller/.ico wants."""
    return [draw_icon(size) for size in sizes]


def set_window_icon(window: "tk.Misc") -> None:
    """Apply the app icon to a Tk window's title bar and taskbar entry.

    Builds PhotoImages at a few sizes so Tk/Windows can pick the closest
    match for the title bar versus Alt-Tab versus the taskbar, and keeps a
    reference on the window itself: Tk keeps none of its own, and a
    garbage-collected PhotoImage silently reverts to the default icon (the
    same gotcha overlay.py's picture labels already have to work around).
    """
    from PIL import ImageTk

    # master= is not optional. A PhotoImage with no master binds to
    # tkinter._default_root -- the hidden pump root in app.py -- while
    # iconphoto runs on this window's own interpreter, and Tk rejects the
    # image with "can't use pyimage1 as iconphoto: not a photo image". Same
    # root cause as the master-less variables fixed in F1.
    try:
        photos = [
            ImageTk.PhotoImage(draw_icon(size), master=window)
            for size in (16, 32, 48, 64)
        ]
        # Tk keeps no reference of its own; a collected PhotoImage silently
        # reverts to the default icon.
        window._stfu_icon_refs = photos  # type: ignore[attr-defined]
        window.iconphoto(True, *photos)
    except Exception:
        # An icon is decoration. A window that refuses to open because its
        # decoration failed is a broken app -- this exact failure left a bare
        # untitled window where the PIN prompt should have been.
        log.exception("could not apply the app icon")
