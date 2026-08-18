"""PIN entry, and the gate that guards the protected tray actions."""

from __future__ import annotations

import tkinter as tk
from tkinter import simpledialog

from stfu.config import Config, verify_pin


def ask_pin(title: str = "S.TFU", prompt: str = "PIN:") -> str | None:
    """Modal PIN prompt. Returns None if cancelled."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return simpledialog.askstring(title, prompt, show="*", parent=root)
    finally:
        root.destroy()


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

    An honest speed bump, not a security boundary: anyone with admin rights can
    end any process, and that is understood.
    """
    entered = ask_pin()
    if entered is None:
        return False
    return verify_pin(entered, config.pin_hash, config.pin_salt)
