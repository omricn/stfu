"""PIN entry, and the gate that guards the protected tray actions.

F4: the previous implementation used `simpledialog.askstring`, which requires
pressing Enter or OK even when the typed PIN is already correct. The dialog
here checks the PIN against the stored hash after every keystroke and closes
itself the instant it matches -- Enter and an OK button remain, for a wrong
PIN or for anyone who prefers to type-and-confirm.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from stfu import appicon
from stfu.config import Config, verify_pin


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
        title: str,
        prompt: str,
        verify: Callable[[str], bool] | None = None,
    ) -> None:
        self._verify = verify
        self.result: str | None = None

        self.root = tk.Tk()
        appicon.set_window_icon(self.root)
        self.root.title(title)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._cancel)

        tk.Label(self.root, text=prompt).pack(padx=16, pady=(16, 4))

        self._var = tk.StringVar(master=self.root, value="")
        entry = tk.Entry(self.root, textvariable=self._var, show="*", width=20)
        entry.pack(padx=16, pady=4)
        entry.bind("<KeyRelease>", self._on_key)
        entry.bind("<Return>", lambda _e: self._submit())

        self._hint = tk.Label(self.root, text="", fg="#a00000")
        self._hint.pack(padx=16)

        buttons = tk.Frame(self.root)
        buttons.pack(pady=(4, 16))
        tk.Button(buttons, text="OK", command=self._submit).pack(side="left", padx=4)
        tk.Button(buttons, text="Cancel", command=self._cancel).pack(
            side="left", padx=4
        )

        entry.focus_set()

    def show(self) -> str | None:
        self.root.mainloop()
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


def ask_pin(title: str = "S.TFU", prompt: str = "PIN:") -> str | None:
    """Modal PIN prompt with no live verification. Returns None if cancelled.

    Used only where there is nothing yet to check the entry against -- see
    `ask_new_pin`. The tray's own PIN check is `gate`, below, which verifies
    on each keystroke.
    """
    return _PinDialog(title, prompt).show()


def ask_new_pin() -> str | None:
    """Ask twice and require a match. None if cancelled or mismatched."""
    first = ask_pin(prompt="Choose a PIN:")
    if not first:
        return None
    second = ask_pin(prompt="Confirm the PIN:")
    if first != second:
        return None
    return first


def gate(config: Config) -> bool:
    """True if the user entered the right PIN.

    Verifies on each keystroke and closes the dialog the instant the PIN is
    correct -- no Enter needed (F4).

    An honest speed bump, not a security boundary: anyone with admin rights
    can end any process, and that is understood.
    """
    result = _PinDialog(
        "S.TFU",
        "PIN:",
        verify=lambda pin: verify_pin(pin, config.pin_hash, config.pin_salt),
    ).show()
    if result is None:
        return False
    return verify_pin(result, config.pin_hash, config.pin_salt)
