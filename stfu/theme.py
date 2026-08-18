"""The S.TFU palette and dark ttk theme (see docs/BRAND.md).

Pure constants plus one function, `apply(root)`, that configures ttk styles
on a given root/Toplevel. This module draws nothing and opens no windows --
it is safe to import from anywhere a screen module already imports tkinter,
but it is not itself a screen.

**Where Tk will not follow.** Classic `tk` widgets (`tk.Entry`, `tk.Listbox`,
`tk.Label`, `tk.Button`, `tk.Frame`, `tk.Canvas`, ...) do not use ttk styles
at all -- they are coloured directly with `bg=`/`fg=` wherever they appear,
and `apply()` cannot reach them. Conversely, a few `ttk` widgets on Windows's
native themes ignore background colour entirely regardless of style
(`ttk.Combobox`'s text field under `vista`/`winnative`, for instance, and the
combobox's popdown listbox is a plain `tk.Listbox` Tk builds internally, not
styled by ttk at all). `apply()` below switches to ttk's `clam` theme
specifically because it is the one built-in theme that actually honours
custom colours on Windows -- `vista` and `winnative` mostly do not. Even
under `clam`, the combobox popdown listbox needs its own `option_add` call
(done below) because it is not a themable ttk element.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# --- palette -----------------------------------------------------------

INK = "#0d0d10"  # window background
SURFACE = "#16161b"  # cards, form rows, input wells
SURFACE_HI = "#1f1f26"  # hover, selected rows, the meter's track
HAIRLINE = "#2a2a33"  # borders, dividers, the faint concentric rings

INDIGO = "#6c63f5"  # primary accent -- outer bars, the dots in S.T.F.U
AMBER = "#f5a623"  # mid bars, warnings, the paused state
RED = "#ef4136"  # centre bar, the trigger itself, over-threshold, destructive

TEXT = "#f2f2f5"  # primary text
TEXT_DIM = "#8a8a95"  # secondary text, the tagline, help copy

GREEN = "#3ddc84"  # listening / healthy -- tray-only, not part of the mark

# The three accents, in the order the brand fixes them: calm/outer to
# peak/centre. The meter and the report chart both read this list rather
# than picking colours ad hoc, so "what does red mean" stays answered once.
ACCENT_ORDER = (INDIGO, AMBER, RED)

# --- type ----------------------------------------------------------------
# Segoe UI throughout -- it ships on every Windows machine. Tk falls back
# silently (no exception) if a named family variant is missing, so the
# lighter/semibold family names below degrade gracefully to plain Segoe UI
# rather than breaking anything.

FONT_TITLE = ("Segoe UI Semibold", 22)
FONT_HEADING = ("Segoe UI Semibold", 13)
FONT_BODY = ("Segoe UI", 10)
FONT_WORDMARK = ("Segoe UI Light", 28)
FONT_TAGLINE = ("Segoe UI", 8)


def letter_spaced(text: str, gap: str = " ") -> str:
    """Insert a thin space between every character.

    Tk has no letter-spacing/tracking property, so the wordmark's and
    tagline's wide tracking -- the logo's most recognisable typographic
    trait -- is faked by interleaving a thin space (U+2009) between letters.
    A plain ASCII space is too wide at these sizes; a thin space reads as
    tracking rather than as separate words.
    """
    return gap.join(text)


def _configure_combobox_popdown(root: tk.Misc) -> None:
    """Style the combobox dropdown list.

    The popdown is a plain `tk.Listbox` ttk builds on demand, not a themable
    ttk element -- `style.configure` cannot touch it. `option_add` is the
    only lever Tk exposes for it, and it is process/interpreter-wide rather
    than per-widget, which is fine here since there is exactly one
    interpreter in the whole app (see app.py).
    """
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", INDIGO)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)


def apply(root: tk.Misc) -> ttk.Style:
    """Configure ttk styles for the dark theme on `root`'s interpreter.

    Idempotent and cheap enough to call once per Toplevel -- `ttk.Style()`
    reads the same interpreter-wide style database every time, it does not
    create a second one, so calling this from several screens is harmless.
    """
    style = ttk.Style(root)
    # clam is the one bundled theme whose colours ttk widgets actually honour
    # on Windows -- see the module docstring.
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=INK, foreground=TEXT, font=FONT_BODY)

    style.configure("TFrame", background=INK)
    style.configure("Surface.TFrame", background=SURFACE)

    style.configure("TLabel", background=INK, foreground=TEXT, font=FONT_BODY)
    style.configure("Surface.TLabel", background=SURFACE, foreground=TEXT)
    style.configure(
        "Dim.TLabel", background=INK, foreground=TEXT_DIM, font=FONT_BODY
    )
    style.configure(
        "Heading.TLabel",
        background=INK,
        foreground=TEXT_DIM,
        font=FONT_HEADING,
    )
    style.configure(
        "Title.TLabel", background=INK, foreground=TEXT, font=FONT_TITLE
    )

    style.configure(
        "TButton",
        background=SURFACE_HI,
        foreground=TEXT,
        bordercolor=HAIRLINE,
        focuscolor=INDIGO,
        padding=(10, 6),
    )
    style.map(
        "TButton",
        background=[("active", HAIRLINE), ("pressed", HAIRLINE)],
        foreground=[("disabled", TEXT_DIM)],
    )
    style.configure(
        "Accent.TButton",
        background=INDIGO,
        foreground=TEXT,
        padding=(10, 6),
    )
    style.map(
        "Accent.TButton",
        background=[("disabled", SURFACE_HI), ("active", "#5951d1")],
        foreground=[("disabled", TEXT_DIM)],
    )

    style.configure(
        "TEntry",
        fieldbackground=SURFACE,
        foreground=TEXT,
        insertcolor=TEXT,
        bordercolor=HAIRLINE,
        lightcolor=HAIRLINE,
        darkcolor=HAIRLINE,
    )
    style.map("TEntry", fieldbackground=[("readonly", SURFACE)])

    style.configure(
        "TCombobox",
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=TEXT,
        arrowcolor=TEXT_DIM,
        bordercolor=HAIRLINE,
        selectbackground=SURFACE,
        selectforeground=TEXT,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", SURFACE)],
        foreground=[("readonly", TEXT)],
    )
    _configure_combobox_popdown(root)

    style.configure(
        "TCheckbutton", background=INK, foreground=TEXT, focuscolor=INDIGO
    )
    style.map("TCheckbutton", background=[("active", INK)])

    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        bordercolor=HAIRLINE,
        rowheight=24,
    )
    style.map(
        "Treeview",
        background=[("selected", INDIGO)],
        foreground=[("selected", TEXT)],
    )
    style.configure(
        "Treeview.Heading",
        background=SURFACE_HI,
        foreground=TEXT_DIM,
        bordercolor=HAIRLINE,
        relief="flat",
    )
    style.map("Treeview.Heading", background=[("active", SURFACE_HI)])

    style.configure(
        "TScrollbar",
        background=SURFACE_HI,
        troughcolor=INK,
        bordercolor=INK,
        arrowcolor=TEXT_DIM,
    )
    style.map("TScrollbar", background=[("active", HAIRLINE)])

    style.configure(
        "TProgressbar",
        background=INDIGO,
        troughcolor=SURFACE_HI,
        bordercolor=SURFACE_HI,
        lightcolor=INDIGO,
        darkcolor=INDIGO,
    )

    return style
