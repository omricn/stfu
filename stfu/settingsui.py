"""The settings window: a form over the operator-facing Config fields.

Every value round-trips through save_config/load_config, so _coerce is the
single source of truth for what "valid" means -- this window does not
duplicate that logic, it just writes what was typed and reloads.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

from stfu import appicon, autostart
from stfu.calibrationui import CalibrationDialog
from stfu.config import (
    SESSION_RESET_MODES,
    THRESHOLD_MODES,
    Config,
    data_dir,
    load_config,
    save_config,
)
from stfu.sounds import RUNG_FIRST, ClipLibrary, MiniaudioPlayer, SoundBite

log = logging.getLogger(__name__)


class SettingsWindow:
    """One form, one Save. Closing any other way discards changes."""

    def __init__(self, master: tk.Misc, config: Config) -> None:
        self.master = master
        self.config = config
        self.root: tk.Toplevel | None = None
        self._status: tk.Label | None = None
        self._calibration: CalibrationDialog | None = None

        # Text-entry fields, keyed by Config attribute name.
        self._fields: dict[str, tk.StringVar] = {}
        # Checkbutton fields.
        self._bools: dict[str, tk.BooleanVar] = {}

    def show(self) -> None:
        self.root = tk.Toplevel(self.master)
        appicon.set_window_icon(self.root)
        self.root.title("S.TFU settings")

        # Come to the front once, without staying pinned there. A window that
        # silently opened behind a still-showing overlay looked exactly like a
        # window that never opened at all.
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(200, lambda: self.root.attributes("-topmost", False))

        self.root.geometry("520x620")
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        # The form scrolls. It already holds twenty rows and every new setting
        # adds another; a fixed frame would quietly push the Save button off a
        # smaller screen.
        canvas = tk.Canvas(self.root, highlightthickness=0)
        scrollbar = tk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        form = tk.Frame(canvas)

        form.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window = canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.bind(
            "<Configure>", lambda e: canvas.itemconfigure(window, width=e.width)
        )
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(16, 0), pady=12)
        scrollbar.pack(side="right", fill="y", pady=12)
        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"),
        )

        self._add_choice(form, "threshold_mode", "Threshold mode", THRESHOLD_MODES)
        self._add_entry(form, "spike_threshold_dbfs", "Spike threshold (dBFS)")
        self._add_bool(form, "sustain_enabled", "Sustain detection enabled")
        self._add_entry(form, "sustain_threshold_dbfs", "Sustain threshold (dBFS)")
        self._add_entry(form, "cooldown_seconds", "Cooldown (seconds)")
        self._add_choice(
            form, "session_reset_mode", "Session reset", SESSION_RESET_MODES
        )
        self._add_entry(form, "rolling_reset_minutes", "Rolling reset (minutes)")
        self._add_entry(form, "nightly_reset_hour", "Nightly reset hour (0-23)")
        self._add_entry(form, "overlay_strikes", "Popups before desktop drop")
        # Turning both of these off leaves detection and logging running with
        # no interruption at all -- worth a night before letting it react.
        self._add_bool(form, "popups_enabled", "Show popups")
        self._add_bool(form, "sound_enabled", "Play sounds")
        self._add_entry(form, "overlay_clicks_required", "Overlay clicks required")
        self._add_entry(form, "desktop_message_seconds", "Desktop message (seconds)")
        self._add_entry(form, "sound_gain", "Sound gain")
        self._add_entry(form, "max_clip_seconds", "Max clip length (seconds)")
        self._add_entry(form, "spike_window_ms", "Spike window (ms)")
        self._add_entry(form, "sustain_window_ms", "Sustain window (ms)")
        self._add_entry(form, "adaptive_delta_db", "Adaptive: dB above baseline")
        self._add_entry(form, "adaptive_min_threshold_dbfs", "Adaptive: floor (dBFS)")
        self._add_entry(form, "adaptive_max_threshold_dbfs", "Adaptive: ceiling (dBFS)")
        self._add_entry(form, "adaptive_baseline_minutes", "Adaptive: baseline (minutes)")
        self._add_autostart(form)

        self._status = tk.Label(self.root, text="", anchor="w", fg="#555555")
        self._status.pack(fill="x", padx=16)

        buttons = tk.Frame(self.root)
        buttons.pack(fill="x", padx=16, pady=12)
        tk.Button(buttons, text="Test sound", command=self._test_sound).pack(
            side="left"
        )
        tk.Button(buttons, text="Recalibrate", command=self._recalibrate).pack(
            side="left", padx=(8, 0)
        )
        tk.Button(buttons, text="Cancel", command=self._close).pack(side="right")
        tk.Button(buttons, text="Save", command=self._save).pack(
            side="right", padx=(0, 8)
        )

    # --- form construction ----------------------------------------------

    def _add_entry(self, parent: tk.Frame, name: str, label: str) -> None:
        row = tk.Frame(parent)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, width=26, anchor="w").pack(side="left")
        var = tk.StringVar(master=self.root, value=str(getattr(self.config, name)))
        tk.Entry(row, textvariable=var, width=14).pack(side="left")
        self._fields[name] = var

    def _add_choice(self, parent: tk.Frame, name: str, label: str, values) -> None:
        row = tk.Frame(parent)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, width=26, anchor="w").pack(side="left")
        var = tk.StringVar(master=self.root, value=getattr(self.config, name))
        ttk.Combobox(
            row, textvariable=var, values=list(values), state="readonly", width=14
        ).pack(side="left")
        self._fields[name] = var

    def _add_bool(self, parent: tk.Frame, name: str, label: str) -> None:
        var = tk.BooleanVar(master=self.root, value=bool(getattr(self.config, name)))
        tk.Checkbutton(parent, text=label, variable=var).pack(anchor="w", pady=4)
        self._bools[name] = var

    def _add_autostart(self, parent: tk.Frame) -> None:
        var = tk.BooleanVar(master=self.root, value=bool(self.config.autostart))

        def toggle() -> None:
            enabled = bool(var.get())
            if enabled:
                autostart.enable(autostart.executable_path())
            else:
                autostart.disable()
            self._set_status(
                "Autostart enabled." if enabled else "Autostart disabled."
            )

        tk.Checkbutton(
            parent,
            text="Start S.TFU when Windows starts",
            variable=var,
            command=toggle,
        ).pack(anchor="w", pady=4)
        self._bools["autostart"] = var

    # --- actions -----------------------------------------------------------

    def _set_status(self, text: str) -> None:
        if self._status is not None:
            self._status.configure(text=text)

    def _save(self) -> None:
        for name, var in self._fields.items():
            raw = var.get()
            current = getattr(self.config, name)
            if isinstance(current, float):
                try:
                    setattr(self.config, name, float(raw))
                except ValueError:
                    pass
            elif isinstance(current, int):
                try:
                    setattr(self.config, name, int(raw))
                except ValueError:
                    pass
            else:
                setattr(self.config, name, raw)

        for name, var in self._bools.items():
            setattr(self.config, name, bool(var.get()))

        # Round-trip through disk so _coerce validates whatever was typed --
        # anything nonsensical is replaced with a safe default, never with
        # something that silently disables detection.
        save_config(self.config)
        self.config = load_config()
        for name, var in self._fields.items():
            var.set(str(getattr(self.config, name)))
        for name, var in self._bools.items():
            var.set(bool(getattr(self.config, name)))
        self._set_status("Saved.")

    def _close(self) -> None:
        if self.root:
            self.root.destroy()

    def _test_sound(self) -> None:
        sounds_root = data_dir() / "sounds"
        try:
            gain = float(self._fields["sound_gain"].get())
        except ValueError:
            gain = self.config.sound_gain
        try:
            max_seconds = float(self._fields["max_clip_seconds"].get())
        except ValueError:
            max_seconds = self.config.max_clip_seconds

        bite = SoundBite(
            ClipLibrary(sounds_root), MiniaudioPlayer(), gain=gain,
            max_seconds=max_seconds,
        )
        duration = bite.play(RUNG_FIRST)
        self._set_status(
            "Playing..." if duration is not None else "No sound clips found."
        )

    def _recalibrate(self) -> None:
        """Open the shared recalibration dialog (see calibrationui.py) as a
        child of this window.

        Only updates the in-memory form fields -- like everything else here,
        it takes effect only if the operator then presses Save. A press
        while a previous run is still going cancels that one first, so it
        cannot keep the microphone open underneath the new dialog.
        """
        if self._calibration is not None:
            self._calibration.cancel()

        def apply_result(result) -> None:
            self._fields["spike_threshold_dbfs"].set(str(result.spike_threshold_dbfs))
            self._fields["sustain_threshold_dbfs"].set(
                str(result.sustain_threshold_dbfs)
            )

        self._calibration = CalibrationDialog(
            self.config,
            on_result=apply_result,
            success_suffix=" Press Save on the main window to keep it.",
        )
        self._calibration.show(master=self.root)
