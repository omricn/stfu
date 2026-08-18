"""PIN entry, and the gate that guards the protected tray actions.

F4: the previous implementation used `simpledialog.askstring`, which requires
pressing Enter or OK even when the typed PIN is already correct. The dialog
here checks the PIN against the stored hash after every keystroke and closes
itself the instant it matches -- Enter and an OK button remain, for a wrong
PIN or for anyone who prefers to type-and-confirm.

This dialog is a Toplevel of the caller's `master` (app.py's one Tk root),
never its own Tk(). `gate()` genuinely needs the result before it can return,
so it uses `master.wait_window()` -- the Tk-supported way to block until a
window closes -- rather than a nested mainloop(). A nested mainloop() here
was bug #5: after the PIN was accepted the dialog's own separate interpreter
closed, but the window that was meant to follow never appeared.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from PIL import ImageTk

from stfu import appicon, brand, theme
from stfu.config import Config, verify_pin

MARK_SIZE = 40


class _PinDialog:
    """A small modal PIN entry window.

    With `verify` set, the PIN is checked after every keystroke and the
    dialog closes itself the instant it matches. Enter and the OK button
    still work, re-checking explicitly; on a mismatch they clear the field
    and show a hint rather than closing, so a wrong guess never returns as
    if it had succeeded.

    Without `verify` (used by `ask_pin`/`ask_new_pin`, when *setting* a PIN
    -- there is nothing yet to check the new PIN against) the dialog is a
    plain prompt: Enter or OK submits whatever was typed, correct or not,
    and the caller decides what "correct" means.
    """

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        prompt: str,
        verify: Callable[[str], bool] | None = None,
    ) -> None:
        self.master = master
        self._verify = verify
        self.result: str | None = None

        self.root = tk.Toplevel(master)
        # Title first, then decoration. When the icon call used to throw, it
        # aborted construction and left a bare window captioned "tk" with no
        # widgets in it, which is a far worse failure than a missing icon.
        self.root.title(title)
        appicon.set_window_icon(self.root)
        theme.apply(self.root)
        self.root.configure(bg=theme.INK)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._cancel)

        # Small and centred, the mark above the field (see docs/BRAND.md).
        # master= keeps this PhotoImage bound to this dialog's own
        # interpreter -- see tests/test_tk_variables.py.
        mark_image = brand.draw_mark(MARK_SIZE)
        self._mark_photo = ImageTk.PhotoImage(mark_image, master=self.root)
        tk.Label(self.root, image=self._mark_photo, bg=theme.INK).pack(
            padx=24, pady=(20, 4)
        )

        tk.Label(
            self.root, text=prompt, bg=theme.INK, fg=theme.TEXT, font=theme.FONT_BODY
        ).pack(padx=24, pady=(0, 8))

        self._var = tk.StringVar(master=self.root, value="")
        entry = ttk.Entry(
            self.root, textvariable=self._var, show="*", width=20, justify="center"
        )
        entry.pack(padx=24, pady=4)
        entry.bind("<KeyRelease>", self._on_key)
        entry.bind("<Return>", lambda _e: self._submit())

        self._hint = tk.Label(
            self.root, text="", bg=theme.INK, fg=theme.RED, font=theme.FONT_BODY
        )
        self._hint.pack(padx=24)

        buttons = tk.Frame(self.root, bg=theme.INK)
        buttons.pack(pady=(8, 20))
        ttk.Button(
            buttons, text="OK", command=self._submit, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(
            side="left", padx=4
        )

        entry.focus_set()

    def show(self) -> str | None:
        # wait_window() processes events and returns once self.root is
        # destroyed -- unlike mainloop(), it does not consume a quit() flag
        # shared with app.py's own root, and it does not need to be the
        # innermost loop on the thread to return correctly.
        self.master.wait_window(self.root)
        return self.result

    def _on_key(self, _event=None) -> None:
        if self._verify is None:
            return
        pin = self._var.get()
        # Skip the empty string: it is never correct, and hashing it on every
        # backspace-to-empty is pure waste.
        if pin and self._verify(pin):
            self.result = pin
            self.root.destroy()

    def _submit(self) -> None:
        pin = self._var.get()
        if self._verify is not None and not self._verify(pin):
            self._hint.configure(text="Wrong PIN.")
            self._var.set("")
            return
        self.result = pin
        self.root.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.root.destroy()


def ask_pin(master: tk.Misc, title: str = "S.TFU", prompt: str = "PIN:") -> str | None:
    """Modal PIN prompt with no live verification. Returns None if cancelled.

    Used only where there is nothing yet to check the entry against -- see
    `ask_new_pin`. The tray's own PIN check is `gate`, below, which verifies
    on each keystroke.
    """
    return _PinDialog(master, title, prompt).show()


def ask_new_pin(master: tk.Misc) -> str | None:
    """Ask twice and require a match. None if cancelled or mismatched."""
    first = ask_pin(master, prompt="Choose a PIN:")
    if not first:
        return None
    second = ask_pin(master, prompt="Confirm the PIN:")
    if first != second:
        return None
    return first


def gate(config: Config, master: tk.Misc) -> bool:
    """True if the user entered the right PIN.

    Verifies on each keystroke and closes the dialog the instant the PIN is
    correct -- no Enter needed (F4).

    An honest speed bump, not a security boundary: anyone with admin rights
    can end any process, and that is understood.
    """
    result = _PinDialog(
        master,
        "S.TFU",
        "PIN:",
        verify=lambda pin: verify_pin(pin, config.pin_hash, config.pin_salt),
    ).show()
    if result is None:
        return False
    return verify_pin(result, config.pin_hash, config.pin_salt)
