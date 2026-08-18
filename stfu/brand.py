"""The S.TFU mark: a waveform of rounded vertical bars, tallest at the
centre, falling away symmetrically (see docs/BRAND.md).

Drawn with Pillow the way `appicon.py` already drew the tray's coloured
circles and its own former speaker glyph -- one less binary asset to keep in
sync, path-resolve when frozen, or lose track of. `appicon.py` now renders
the app icon *from this module* (`draw_mark`) rather than its own separate
artwork, so the taskbar, every window's title bar, and the exe itself all
show the same mark as the logo.

This module draws only the mark -- no window, no wordmark text, no tagline.
`splashui.py` prefers the owner-supplied `assets/brand/logo.gif` (which does
carry the wordmark and tagline, baked into its frames) when present, and
falls back to animating this drawn mark only if that file is missing. See
splashui.py for why: a GIF is a fixed frame count and pixel size, resolution-
independent code is not, and code can later be driven by real audio levels
where a GIF cannot.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from stfu.theme import AMBER, INDIGO, RED

# Eight bars, symmetric: indigo (outer, calm) through amber to a red centre
# pair (the trigger itself) -- see BRAND.md's palette table. An even count
# with a matched centre *pair* rather than one single centre bar keeps the
# silhouette perfectly symmetric, which a single centre bar (odd count)
# cannot be while also being "tallest".
BAR_COLOURS = (INDIGO, INDIGO, AMBER, RED, RED, AMBER, INDIGO, INDIGO)
BASE_HEIGHTS = (0.34, 0.55, 0.78, 1.0, 1.0, 0.78, 0.55, 0.34)

# Geometry, as fractions of the rendered size.
_BAR_WIDTH_FRAC = 0.085
_BAR_GAP_FRAC = 0.045
_MAX_BAR_HEIGHT_FRAC = 0.72
_MIN_HEIGHT_FACTOR = 0.18  # a bar never fully vanishes mid-animation

# How far the ripple's phase shifts per bar, moving outward from the centre.
_WAVE_LAG_PER_BAR = 0.16
# Peak-to-peak swing around each bar's resting height.
_WAVE_AMPLITUDE = 0.30

# The smallest fraction of a bar's resting height still shown at level=0 --
# silence reads as a small nub, not a total gap, so the mark stays
# recognisable as the mark rather than disappearing (calibrationui.py: "the
# waveform reacts to the recording level").
_LEVEL_MIN_FACTOR = 0.12

# Supersampled then downsampled with LANCZOS -- Pillow's rounded_rectangle
# has no anti-aliasing of its own, and the pill ends look jagged at the
# small sizes a title-bar or taskbar icon actually renders at (16-32px)
# without this.
_SUPERSAMPLE = 4


def animated_bar_heights(phase: float) -> tuple[float, ...]:
    """Per-bar height, 0..1, at animation position `phase`.

    `phase` advances by 1.0 per full cycle. Each bar's wave is offset by its
    distance from the centre pair, so the rise and fall visibly originates
    in the middle and travels outward -- "centre-outward" per BRAND.md.
    """
    n = len(BASE_HEIGHTS)
    centre = (n - 1) / 2
    heights = []
    for index, base in enumerate(BASE_HEIGHTS):
        distance = abs(index - centre)
        wave = math.sin(2 * math.pi * phase - distance * _WAVE_LAG_PER_BAR)
        factor = 1.0 + _WAVE_AMPLITUDE * wave
        heights.append(max(_MIN_HEIGHT_FACTOR, base * factor))
    return tuple(heights)


def level_bar_heights(level: float) -> tuple[float, ...]:
    """Per-bar height, 0..1, scaled by a live audio level (0..1, already
    normalised by the caller).

    Unlike `animated_bar_heights`, this is not time-driven -- it is one
    instantaneous snapshot of "how loud right now", used by calibrationui.py
    to make the mark itself react to the microphone rather than animate on
    a timer. The bars keep the mark's usual relative proportions
    (BASE_HEIGHTS); only their shared amplitude moves with the level.
    """
    level = max(0.0, min(1.0, level))
    factor = _LEVEL_MIN_FACTOR + (1.0 - _LEVEL_MIN_FACTOR) * level
    return tuple(base * factor for base in BASE_HEIGHTS)


def _render(heights: tuple[float, ...], size: int) -> Image.Image:
    render_size = size * _SUPERSAMPLE
    image = Image.new("RGBA", (render_size, render_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    bar_width = render_size * _BAR_WIDTH_FRAC
    gap = render_size * _BAR_GAP_FRAC
    n = len(heights)
    total_width = n * bar_width + (n - 1) * gap
    start_x = (render_size - total_width) / 2
    max_bar_height = render_size * _MAX_BAR_HEIGHT_FRAC
    mid_y = render_size / 2
    radius = bar_width / 2

    for index, (height_frac, colour) in enumerate(zip(heights, BAR_COLOURS)):
        bar_height = max(bar_width, max_bar_height * height_frac)
        x0 = start_x + index * (bar_width + gap)
        x1 = x0 + bar_width
        y0 = mid_y - bar_height / 2
        y1 = mid_y + bar_height / 2
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=colour)

    if _SUPERSAMPLE != 1:
        image = image.resize((size, size), Image.LANCZOS)
    return image


def draw_mark(size: int, phase: float | None = None) -> Image.Image:
    """Render the waveform mark at `size` x `size`, RGBA, transparent
    background.

    `phase=None` (the default) draws the still, resting mark -- used for the
    app icon and any static placement of the mark on a screen. A numeric
    `phase` (see `animated_bar_heights`) draws one animated frame instead,
    for the drawn-mark fallback splash.
    """
    heights = BASE_HEIGHTS if phase is None else animated_bar_heights(phase)
    return _render(heights, size)


def draw_mark_at_level(size: int, level: float) -> Image.Image:
    """Render the mark scaled to a live audio level (0..1) instead of a time
    phase -- see `level_bar_heights`."""
    return _render(level_bar_heights(level), size)
