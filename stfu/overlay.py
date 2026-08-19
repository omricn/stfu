"""The 4-click overlay and the desktop message.

ClickTracker holds every decision -- how many clicks remain and where the close
button jumps next -- so the deliberately annoying part of the app is unit-tested
without opening a window. The Tk classes only render.
"""

from __future__ import annotations

import logging
import math
import random
import tkinter as tk
from pathlib import Path

from stfu import appicon, brand, theme

log = logging.getLogger(__name__)


class ClickTracker:
    """Counts clicks toward dismissal and places the close button.

    The button must move far enough each time to be visibly somewhere new,
    otherwise four clicks read as a broken button rather than a deliberate
    obstacle.
    """

    def __init__(self, required: int, rng: random.Random | None = None) -> None:
        self.required = max(1, required)
        self.clicks = 0
        self._rng = rng or random.Random()

    @property
    def remaining(self) -> int:
        return max(0, self.required - self.clicks)

    @property
    def done(self) -> bool:
        return self.clicks >= self.required

    def click(self) -> bool:
        """Register a click. True means the overlay should now close."""
        self.clicks += 1
        return self.done

    def next_position(
        self,
        bounds: tuple[int, int],
        size: tuple[int, int],
        current: tuple[int, int] | None = None,
        min_move: float = 200.0,
        attempts: int = 60,
    ) -> tuple[int, int]:
        """A new top-left position for the button, inside `bounds`."""
        max_x = max(0, bounds[0] - size[0])
        max_y = max(0, bounds[1] - size[1])

        for _ in range(attempts):
            candidate = (self._rng.randint(0, max_x), self._rng.randint(0, max_y))
            if current is None:
                return candidate
            if (
                math.hypot(candidate[0] - current[0], candidate[1] - current[1])
                >= min_move
            ):
                return candidate

        if current is None:
            return (max_x, max_y)

        # No random position satisfied min_move -- the window is smaller than
        # the required jump. Take the farthest corner: still a visible move, and
        # always inside the bounds.
        corners = [(0, 0), (max_x, 0), (0, max_y), (max_x, max_y)]
        return max(
            corners, key=lambda c: math.hypot(c[0] - current[0], c[1] - current[1])
        )


OVERLAY_FRACTION = 0.9
# Already dark before the rebrand -- BRAND.md's own note here is "already
# dark, add the mark" -- so this now points at the same INK the rest of the
# app uses instead of its own separate near-black constant.
OVERLAY_BG = theme.INK
OVERLAY_FG = theme.TEXT
BUTTON_SIZE = (140, 48)
IMAGE_FRACTION = (0.5, 0.40)  # of screen width, height
MARK_SIZE = 120

# The two trigger messages, single-sourced here so app.py and cli.py -- the
# only two callers that build these windows -- cannot drift apart the way
# "Volume check"/"Too loud" and any future rewording of it otherwise could.
OVERLAY_MESSAGE = "Shhhhhh!"
DESKTOP_MESSAGE = "Silence!"


def _fullscreen_root(master: tk.Misc, fraction: float | None) -> tk.Toplevel:
    """A borderless, always-on-top, centred window.

    A Toplevel of `master` -- app.py's one Tk root -- never its own Tk(). A
    second interpreter is exactly what made the desktop message's window
    fail to reappear after strikes 3 and 4 (see app.py's module docstring):
    its mainloop() never returned, so the re-entry guard around it never
    cleared. `fraction` of None means true fullscreen; a fraction sizes it
    relative to the screen. Both are override-redirect, so there is no title
    bar to close.
    """
    root = tk.Toplevel(master)
    appicon.set_window_icon(root)
    root.configure(bg=OVERLAY_BG)
    root.overrideredirect(True)
    root.attributes("-topmost", True)

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    if fraction is None:
        width, height, x, y = screen_w, screen_h, 0, 0
    else:
        width = int(screen_w * fraction)
        height = int(screen_h * fraction)
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")

    root.lift()
    root.focus_force()
    return root


def _add_mark(root: tk.Toplevel, rely: float) -> tk.Label:
    """The waveform mark, placed near the top of an overlay window (see
    docs/BRAND.md: "Add the mark, and set the message in the wordmark's
    style"). Each overlay is its own Toplevel, so each needs its own
    PhotoImage built with master=root -- see tests/test_tk_variables.py."""
    from PIL import ImageTk

    mark_image = brand.draw_mark(MARK_SIZE)
    photo = ImageTk.PhotoImage(mark_image, master=root)
    label = tk.Label(root, image=photo, bg=OVERLAY_BG, borderwidth=0)
    # Tk keeps no reference of its own; without this the image is collected
    # and the label renders as an empty gap (the same gotcha the picture
    # labels below already have to work around).
    label.image = photo
    label.place(relx=0.5, rely=rely, anchor="center")
    return label


def _wordmark_style(text: str) -> str:
    """The overlay's own message, set in the wordmark's wide-tracked style
    (see docs/BRAND.md) rather than as running text -- it is a mark-like
    announcement, not a sentence."""
    return theme.letter_spaced(text.upper())


def _load_picture(path: Path | None, root, screen: tuple[int, int]):
    """Load and scale a picture to sit under the text, or None.

    Transparency is composited onto the window background rather than converted
    away: most of the shipped pictures are RGBA, and a plain convert("RGB")
    turns transparent pixels black, which reads as an ugly rectangle around the
    subject.

    Returns a PhotoImage. **The caller must keep a reference to it** -- Tk does
    not, and a garbage-collected PhotoImage renders as an empty gap.
    """
    if path is None:
        return None
    try:
        from PIL import Image, ImageTk

        picture = Image.open(path)
        picture.thumbnail(
            (int(screen[0] * IMAGE_FRACTION[0]), int(screen[1] * IMAGE_FRACTION[1])),
            Image.LANCZOS,
        )
        if picture.mode in ("RGBA", "LA", "P"):
            picture = picture.convert("RGBA")
            backdrop = Image.new("RGB", picture.size, OVERLAY_BG)
            backdrop.paste(picture, mask=picture.split()[-1])
            picture = backdrop
        else:
            picture = picture.convert("RGB")
        # master= for the same reason as appicon: without it the image
        # binds to the wrong interpreter and the label renders empty.
        return ImageTk.PhotoImage(picture, master=root)
    except Exception:
        log.exception("could not load picture %s", path)
        return None


class FourClickOverlay:
    """Near-fullscreen overlay whose close button jumps after every click."""

    def __init__(
        self,
        master: tk.Misc,
        tracker: ClickTracker,
        message: str,
        picture: Path | None = None,
    ) -> None:
        self.master = master
        self.tracker = tracker
        self.message = message
        self.picture = picture

    def show(self) -> tk.Toplevel:
        """Display the overlay and return it immediately -- it does not
        block. The caller finds out when it closes via the Toplevel's own
        <Destroy> event, not by waiting here (see _BridgedWindow in app.py)."""
        root = _fullscreen_root(self.master, OVERLAY_FRACTION)

        # Esc and Alt+F4 are suppressed: with them available, the four clicks
        # are theatre.
        root.protocol("WM_DELETE_WINDOW", lambda: None)
        root.bind("<Escape>", lambda _event: "break")
        root.bind("<Alt-F4>", lambda _event: "break")

        _add_mark(root, rely=0.07)

        tk.Label(
            root,
            text=_wordmark_style(self.message),
            bg=OVERLAY_BG,
            fg=theme.RED,
            font=("Segoe UI", 44, "bold"),
            wraplength=int(root.winfo_screenwidth() * 0.7),
        ).place(relx=0.5, rely=0.20, anchor="center")

        photo = _load_picture(
            self.picture, root, (root.winfo_screenwidth(), root.winfo_screenheight())
        )
        if photo is not None:
            picture_label = tk.Label(root, image=photo, bg=OVERLAY_BG, borderwidth=0)
            # Tk keeps no reference of its own; without this the image is
            # collected and the label renders as an empty gap.
            picture_label.image = photo
            picture_label.place(relx=0.5, rely=0.46, anchor="center")

        counter = tk.Label(
            root,
            text=self._counter_text(),
            bg=OVERLAY_BG,
            fg=theme.TEXT_DIM,
            font=("Segoe UI", 18),
        )
        counter.place(relx=0.5, rely=0.80, anchor="center")

        button = tk.Button(root, text="Close", font=("Segoe UI", 14), width=12, height=2)
        position = {"at": None}

        def move() -> None:
            bounds = (root.winfo_width(), root.winfo_height())
            position["at"] = self.tracker.next_position(
                bounds, BUTTON_SIZE, position["at"]
            )
            button.place(x=position["at"][0], y=position["at"][1])

        def on_click() -> None:
            if self.tracker.click():
                root.destroy()
                return
            counter.configure(text=self._counter_text())
            move()

        button.configure(command=on_click)
        root.update_idletasks()
        move()
        return root

    def _counter_text(self) -> str:
        remaining = self.tracker.remaining
        return f"{remaining} more click{'s' if remaining != 1 else ''} to close"


class DesktopMessage:
    """Fullscreen message that dismisses itself after a set time."""

    def __init__(
        self,
        master: tk.Misc,
        message: str,
        seconds: int,
        picture: Path | None = None,
    ) -> None:
        self.master = master
        self.message = message
        self.seconds = seconds
        self.picture = picture

    def show(self) -> tk.Toplevel:
        """Display the message and return it immediately -- it does not
        block. It still self-dismisses after `seconds` via its own after()
        callback; the caller finds out via <Destroy> (see _BridgedWindow)."""
        root = _fullscreen_root(self.master, None)
        root.protocol("WM_DELETE_WINDOW", lambda: None)

        _add_mark(root, rely=0.14)

        tk.Label(
            root,
            text=_wordmark_style(self.message),
            bg=OVERLAY_BG,
            fg=theme.RED,
            font=("Segoe UI", 52, "bold"),
            wraplength=int(root.winfo_screenwidth() * 0.7),
        ).place(relx=0.5, rely=0.30, anchor="center")

        photo = _load_picture(
            self.picture, root, (root.winfo_screenwidth(), root.winfo_screenheight())
        )
        if photo is not None:
            picture_label = tk.Label(root, image=photo, bg=OVERLAY_BG, borderwidth=0)
            picture_label.image = photo
            picture_label.place(relx=0.5, rely=0.62, anchor="center")

        root.after(int(self.seconds * 1000), root.destroy)
        return root
