"""The app's own icon: a speaker with a mute slash, drawn with Pillow (F7).

Generated rather than checked into the repo as a binary asset, for the same
reason tray.py draws its coloured circles at runtime and stfu.spec built its
placeholder .ico at build time: one less asset to keep in sync, path-resolve
when frozen, or lose track of. This module is the single source of the
artwork -- stfu.spec renders it into the .ico applied to the exe itself, and
every Tk window in this app applies it at runtime via iconphoto so title
bars and the taskbar show it too.

This is a deliberately different, separate piece of artwork from the tray
icon (tray.py): a plain coloured circle there carries live app state (green
listening / amber paused / grey no mic) that a single static app icon can't
express, so the tray keeps its own circles rather than reusing this one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

if TYPE_CHECKING:
    import tkinter as tk

# A dark blue-grey speaker body with a red mute slash. Both shapes are
# simple, large, and high-contrast on purpose -- fine detail (cone ridges,
# little sound-wave arcs) turns to mud once this is scaled down to 16px for
# a title bar, where the flat body-plus-slash silhouette still reads fine.
BODY_COLOUR = "#37474f"
SLASH_COLOUR = "#e53935"

ICON_SIZES = (16, 32, 48, 64, 128, 256)


def draw_icon(size: int) -> Image.Image:
    """Render the app icon at `size` x `size` pixels, RGBA with a transparent
    background."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # The speaker: a driver box (rectangle) merged with a cone (triangle)
    # into one polygon, so there is no seam between the two parts.
    box_width = size * 0.28
    box_height = size * 0.34
    box_left = size * 0.14
    box_top = (size - box_height) / 2
    cone_tip_x = size * 0.60
    draw.polygon(
        [
            (box_left, box_top),
            (box_left + box_width, box_top),
            (cone_tip_x, size * 0.10),
            (cone_tip_x, size * 0.90),
            (box_left + box_width, box_top + box_height),
            (box_left, box_top + box_height),
        ],
        fill=BODY_COLOUR,
    )

    # The mute slash: one thick diagonal bar across the whole icon -- the
    # universal "muted" mark, and legible even at 16px where a circle-slash
    # outline would not be.
    slash_width = max(2, round(size * 0.14))
    draw.line(
        [(size * 0.10, size * 0.14), (size * 0.90, size * 0.86)],
        fill=SLASH_COLOUR,
        width=slash_width,
    )
    return image


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

    photos = [ImageTk.PhotoImage(draw_icon(size)) for size in (16, 32, 48, 64)]
    window._stfu_icon_refs = photos  # type: ignore[attr-defined]
    window.iconphoto(True, *photos)
