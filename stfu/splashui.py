"""The launch splash (see docs/BRAND.md).

Shown on every launch, and before the first-run wizard on first run. It is
pure decoration over an app that starts regardless of what happens here --
see `_show_and_wait`'s docstring in app.py for exactly how that is
sequenced, and the try/except below and around every call site for how a
failure here degrades to simply not showing a splash, the same defensive
posture appicon.py already takes for the window icon.

**Source of the animation.** If `stfu/assets/brand/logo.gif` exists (shipped
in `stfu/assets/brand/`, bundled by stfu.spec) its frames are played back
once, in order, at their own recorded per-frame duration, via
`Image.open(...).seek(n)`. That file is the owner-supplied artwork: 330x234,
97 frames, already carries the S.T.F.U wordmark and tagline baked into its
pixels, and ends on the complete static logo -- nothing is drawn over or
under it. If the file is missing, the bars are drawn and animated in code
instead, from the same geometry as the app icon (`brand.draw_mark`), with
the wordmark and tagline drawn separately since the fallback has no baked-in
text. The fallback is not a placeholder for the gif -- it is
resolution-independent, has no file to keep in sync, and could be driven by
real audio levels later, which a fixed set of gif frames cannot.

**Window shape.** Tk has no native rounded corners or window alpha. This
uses the `-transparentcolor` attribute Tk exposes on Windows: a background
image is drawn with the splash's fill colour inside a rounded rectangle and
a single unlikely-to-occur "key" colour everywhere outside it, then that key
colour is declared transparent for the whole window. Where the drawn pixel
*is* the key colour, the desktop shows through; everywhere else is the
solid, opaque fill. `-transparentcolor` is Windows-only -- this app already
targets Windows exclusively (winapi.py, autostart.py, pystray's win32
backend) -- and the whole thing is wrapped so a TclError here (e.g. running
on a Tk build without the attribute) falls back to a plain rectangular
window rather than no splash at all.
"""

from __future__ import annotations

import logging
import time
import tkinter as tk
from typing import Callable

from PIL import Image, ImageDraw, ImageTk

from stfu import brand, theme
from stfu.assets import assets_dir

log = logging.getLogger(__name__)

GIF_PATH_PARTS = ("brand", "logo.gif")

# Padding around the gif/drawn content, and the progress bar's own geometry.
# The gif is shown at its native size -- see the module docstring in
# docs/BRAND.md: upscaling a gif's flat colour looks worse than showing it
# small and sharp.
PAD_X = 28
PAD_TOP = 24
PROGRESS_MARGIN_TOP = 18
PROGRESS_HEIGHT = 8
PROGRESS_MARGIN_BOTTOM = 22
CORNER_RADIUS = 12

# A colour vanishingly unlikely to appear in either the gif's palette or the
# drawn fallback's ink/indigo/amber/red -- see the module docstring for why
# it has to be something, not nothing.
_TRANSPARENT_KEY = "#ff00fe"

# The drawn fallback's own layout (BRAND.md's original ~480x420 dark splash),
# used only when the gif is missing.
_FALLBACK_SIZE = (480, 420)
_FALLBACK_MARK_SIZE = 160
_FALLBACK_DURATION_S = 1.8
_FALLBACK_FRAME_MS = 40

# The gif is played through once at its own recorded speed, not looped, and
# is stopped early only by a click -- see the module docstring on why a
# ~3.9s asset is acceptable here (it never delays the app itself).
_MAX_GIF_MS = 15_000  # a hard ceiling if a corrupt gif reports no frames


def _brightness(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def _rounded_background(
    size: tuple[int, int], radius: int, fill: tuple[int, int, int]
) -> Image.Image:
    """A `size` image: `fill` inside a rounded rectangle, `_TRANSPARENT_KEY`
    everywhere outside it -- see the module docstring on window shaping."""
    key_rgb = tuple(int(_TRANSPARENT_KEY[i : i + 2], 16) for i in (1, 3, 5))
    image = Image.new("RGB", size, key_rgb)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        [0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=fill
    )
    return image


class SplashWindow:
    """Builds the splash and returns immediately, the same non-blocking
    `show()` convention every other window in this app follows (see
    `_BridgedWindow` in app.py) -- it self-animates and self-closes via its
    own `after()` ticks and a click handler, without anything else needing
    to pump it specially.

    That convention is what lets app.py use this same class two different
    ways: on every normal launch it is shown on the app's own hidden root
    *after* the capture and tray threads are already running, as pure
    decoration layered on top of an app that does not need it to finish
    anything. On first run there is no app yet to layer it over, so app.py
    additionally blocks on the returned Toplevel with `wait_window` before
    building the wizard's own separate `Tk()` -- see app.py's module
    docstring on why only one Tk() may be alive at a time.
    """

    def __init__(self, master: tk.Misc) -> None:
        self.master = master
        self.root: tk.Toplevel | None = None
        self._closed = False
        self._after_id: str | None = None
        # PhotoImages have no reference of their own, and Tk silently
        # reverts to a blank image the moment one is garbage-collected (the
        # same gotcha appicon.py and overlay.py already have to work
        # around). Two separate lists on purpose, not one: the rounded
        # background is built once and must outlive the whole splash, while
        # each animation frame is replaced dozens of times a second and only
        # the latest one or two need to survive. A single shared list here,
        # pruned for the animation frames' sake, silently evicted and
        # garbage-collected the *background* photo after only two frames --
        # the window then fell back to Tk's plain default grey for the rest
        # of the splash, invisibly, with no exception raised anywhere. Found
        # by screenshotting a real window, not by the test suite.
        self._image_refs: list[ImageTk.PhotoImage] = []
        self._frame_refs: list[ImageTk.PhotoImage] = []

    def show(self) -> tk.Toplevel | None:
        """Build and start animating the splash. Returns the Toplevel, or
        None if anything about building it failed -- logged, never raised,
        exactly as appicon.py treats a failed icon: decoration must not be
        able to break or block the app around it."""
        try:
            return self._build_and_run()
        except Exception:
            log.exception("splash failed; skipping it")
            if self.root is not None:
                try:
                    self.root.destroy()
                except Exception:
                    pass
            return None

    # --- construction --------------------------------------------------

    def _build_and_run(self) -> tk.Toplevel:
        gif_path = assets_dir().joinpath(*GIF_PATH_PARTS)
        frames = None
        if gif_path.is_file():
            try:
                frames = _load_gif_frames(gif_path)
            except Exception:
                log.exception("could not read %s; using the drawn fallback", gif_path)
                frames = None

        if frames is not None:
            return self._run_gif(frames)
        return self._run_drawn()

    def _new_root(self, size: tuple[int, int], fill_rgb: tuple[int, int, int]) -> tk.Toplevel:
        root = tk.Toplevel(self.master)
        self.root = root
        root.overrideredirect(True)
        root.attributes("-topmost", True)

        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = (screen_w - size[0]) // 2
        y = (screen_h - size[1]) // 2
        root.geometry(f"{size[0]}x{size[1]}+{x}+{y}")

        try:
            root.configure(bg=_TRANSPARENT_KEY)
            root.wm_attributes("-transparentcolor", _TRANSPARENT_KEY)
            background = _rounded_background(size, CORNER_RADIUS, fill_rgb)
        except tk.TclError:
            # No -transparentcolor support: a plain rectangular window still
            # shows the splash, just without rounded corners.
            log.warning("window shaping unavailable; splash will have square corners")
            fill_hex = "#%02x%02x%02x" % fill_rgb
            root.configure(bg=fill_hex)
            background = Image.new("RGB", size, fill_rgb)

        bg_photo = ImageTk.PhotoImage(background, master=root)
        self._image_refs.append(bg_photo)
        bg_label = tk.Label(root, image=bg_photo, borderwidth=0)
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)

        self._bind_dismiss(root)
        self._bind_dismiss(bg_label)
        root.lift()
        return root

    def _bind_dismiss(self, widget: tk.Misc) -> None:
        widget.bind("<Button-1>", lambda _e: self._dismiss())

    def _dismiss(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._after_id is not None and self.root is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
        if self.root is not None:
            self.root.destroy()

    # --- the gif path ----------------------------------------------------

    def _run_gif(self, frames: list["_Frame"]) -> tk.Toplevel:
        first = frames[0].image
        # Every frame was already decoded to RGB by _load_gif_frames, so
        # this is a plain (r, g, b) tuple -- the actual pixel the gif itself
        # paints there, not an assumption. See the module docstring: this is
        # deliberately not a hardcoded dark constant, because this asset
        # happens to be the *light* logo (white corners), not the dark one
        # docs/BRAND.md was drafted against. A dark gif dropped in later
        # needs no code change here.
        fill_rgb = first.getpixel((0, 0))

        gif_w, gif_h = first.size
        content_w = gif_w
        width = content_w + 2 * PAD_X
        height = (
            PAD_TOP + gif_h + PROGRESS_MARGIN_TOP + PROGRESS_HEIGHT + PROGRESS_MARGIN_BOTTOM
        )

        root = self._new_root((width, height), fill_rgb)
        fill_hex = "#%02x%02x%02x" % fill_rgb

        # bg= matters even though the gif frames are fully opaque: without
        # it the label defaults to Tk's own grey, which would show as a
        # one-pixel fringe at the label's edge before the first frame is set
        # and reappear if a frame's own decode ever fails.
        gif_label = tk.Label(root, borderwidth=0, highlightthickness=0, bg=fill_hex)
        gif_label.place(x=PAD_X, y=PAD_TOP)
        self._bind_dismiss(gif_label)

        bar_y = PAD_TOP + gif_h + PROGRESS_MARGIN_TOP
        progress = self._make_progress_bar(root, content_w, fill_rgb)
        progress.place(x=PAD_X, y=bar_y)

        total_ms = min(_MAX_GIF_MS, sum(f.duration_ms for f in frames))
        start = time.monotonic()

        def tick(index: int) -> None:
            if self._closed or self.root is None:
                return
            frame = frames[index % len(frames)]
            photo = ImageTk.PhotoImage(frame.image.convert("RGB"), master=root)
            self._frame_refs.append(photo)
            # Only the newest frame needs to stay referenced; drop the rest
            # so memory does not grow across all 97 frames. This list never
            # holds the background photo -- see __init__.
            if len(self._frame_refs) > 2:
                self._frame_refs.pop(0)
            gif_label.configure(image=photo)

            elapsed_ms = (time.monotonic() - start) * 1000
            self._set_progress(progress, min(1.0, elapsed_ms / total_ms))

            next_index = index + 1
            if next_index >= len(frames) or elapsed_ms >= total_ms:
                self._after_id = root.after(frame.duration_ms, self._dismiss)
                return
            self._after_id = root.after(
                frame.duration_ms, lambda: tick(next_index)
            )

        tick(0)
        return root

    # --- the drawn fallback ------------------------------------------------

    def _run_drawn(self) -> tk.Toplevel:
        # BRAND.md's dark splash assumed the dark artwork; the fallback has
        # no photograph to sample a background from, so it keeps that
        # original assumption (INK) rather than guessing.
        fill_rgb = tuple(int(theme.INK[i : i + 2], 16) for i in (1, 3, 5))
        width, height = _FALLBACK_SIZE
        root = self._new_root((width, height), fill_rgb)

        # bg=theme.INK matters: brand.draw_mark's image is RGBA with a
        # transparent background, and a Label with no bg of its own shows
        # Tk's plain grey through those transparent pixels instead of the
        # splash's own fill colour -- the same class of bug the shared
        # image-ref list above was (see __init__ on that one).
        mark_label = tk.Label(
            root, borderwidth=0, highlightthickness=0, bg=theme.INK
        )
        mark_label.place(relx=0.5, y=48, anchor="n")
        self._bind_dismiss(mark_label)

        wordmark = tk.Label(
            root,
            text=theme.letter_spaced("S.T.F.U"),
            font=theme.FONT_WORDMARK,
            fg=theme.TEXT,
            bg=theme.INK,
        )
        wordmark.place(relx=0.5, y=232, anchor="n")
        self._bind_dismiss(wordmark)

        tagline = tk.Label(
            root,
            text=theme.letter_spaced("SOUND TRIGGER FOCUS UTILITY"),
            font=theme.FONT_TAGLINE,
            fg=theme.TEXT_DIM,
            bg=theme.INK,
        )
        tagline.place(relx=0.5, y=272, anchor="n")
        self._bind_dismiss(tagline)

        progress = self._make_progress_bar(root, width - 2 * PAD_X, fill_rgb)
        progress.place(x=PAD_X, y=height - PROGRESS_MARGIN_BOTTOM - PROGRESS_HEIGHT)

        start = time.monotonic()
        total_s = _FALLBACK_DURATION_S

        def tick() -> None:
            if self._closed or self.root is None:
                return
            elapsed = time.monotonic() - start
            phase = elapsed / total_s
            mark = brand.draw_mark(_FALLBACK_MARK_SIZE, phase=phase)
            photo = ImageTk.PhotoImage(mark, master=root)
            self._frame_refs.append(photo)
            if len(self._frame_refs) > 2:
                self._frame_refs.pop(0)
            mark_label.configure(image=photo)

            self._set_progress(progress, min(1.0, elapsed / total_s))

            if elapsed >= total_s:
                self._dismiss()
                return
            self._after_id = root.after(_FALLBACK_FRAME_MS, tick)

        tick()
        return root

    # --- the shared tri-colour progress bar -------------------------------

    def _make_progress_bar(
        self, root: tk.Toplevel, width: int, bg_rgb: tuple[int, int, int]
    ) -> tk.Canvas:
        # A light splash needs a visibly darker track than a dark one does,
        # and vice versa -- one fixed track colour would disappear against
        # roughly half of all possible splash backgrounds.
        track = "#d8d8dc" if _brightness(bg_rgb) > 128 else theme.SURFACE_HI
        bg_hex = "#%02x%02x%02x" % bg_rgb
        canvas = tk.Canvas(
            root,
            width=width,
            height=PROGRESS_HEIGHT,
            bg=bg_hex,
            highlightthickness=0,
        )
        canvas.track_id = canvas.create_rectangle(
            0, 0, width, PROGRESS_HEIGHT, fill=track, width=0
        )
        third = width / 3
        canvas.segment_ids = tuple(
            canvas.create_rectangle(third * i, 0, third * i, PROGRESS_HEIGHT, width=0)
            for i in range(3)
        )
        canvas.segment_width = third
        self._bind_dismiss(canvas)
        return canvas

    @staticmethod
    def _set_progress(canvas: tk.Canvas, fraction: float) -> None:
        """Fill the three segments in order -- indigo, then amber, then red
        -- rather than blending all three across the whole width at once, so
        the bar reads as three stages completing rather than one gradient."""
        third = canvas.segment_width
        for index, colour in enumerate(theme.ACCENT_ORDER):
            stage_fraction = max(0.0, min(1.0, fraction * 3 - index))
            x0 = third * index
            x1 = x0 + third * stage_fraction
            canvas.coords(canvas.segment_ids[index], x0, 0, x1, PROGRESS_HEIGHT)
            canvas.itemconfigure(canvas.segment_ids[index], fill=colour)


class _Frame:
    __slots__ = ("image", "duration_ms")

    def __init__(self, image: Image.Image, duration_ms: int) -> None:
        self.image = image
        self.duration_ms = duration_ms


def _load_gif_frames(path) -> list[_Frame]:
    """Every frame of the gif, decoded up front, each tagged with its own
    recorded duration (gif frames may not share one).

    Decoded eagerly rather than lazily re-seeking one shared Image on every
    tick: a 330x234 97-frame gif is a few tens of megabytes fully decoded,
    trivial to hold for the ~4s the splash is on screen, and it means a
    corrupt frame is caught here -- before anything is on screen -- rather
    than mid-animation.
    """
    frames: list[_Frame] = []
    with Image.open(path) as gif:
        n_frames = getattr(gif, "n_frames", 1)
        for index in range(n_frames):
            gif.seek(index)
            duration = int(gif.info.get("duration", 40)) or 40
            frames.append(_Frame(gif.convert("RGB"), duration))
    return frames
