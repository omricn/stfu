"""The recalibration dialog: three short recordings that produce a fresh
pair of thresholds.

Extracted out of SettingsWindow (F3) so the tray's "Recalibrate" item can
open this flow directly instead of detouring through the whole settings
window, while the settings window's own Recalibrate button keeps working by
opening the same class as a child of its own window.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from PIL import ImageTk

from stfu import appicon, brand, theme
from stfu.audio import MicSource
from stfu.calibration import (
    CalibrationResult,
    CalibrationSamples,
    collect_sample,
    compute_thresholds,
)
from stfu.config import Config
from stfu.levels import meter_from_dbfs

SAMPLE_SECONDS = {"quiet": 10, "speech": 10, "yell": 5}
FRAMES_PER_SECOND = 50
MARK_SIZE = 72


class CalibrationDialog:
    """Runs the three-sample calibration flow in a small window.

    `show(master)` builds a Toplevel of `master` and returns immediately --
    it does not block. `master` is always app.py's one Tk root or a Toplevel
    of it (e.g. SettingsWindow's own window when opened via its Recalibrate
    button); there is no standalone Tk()-owning mode any more.

    `on_result` is called on the Tk thread with the CalibrationResult once a
    run finishes -- the caller decides what to do with it (the settings
    window fills in its own form fields; a standalone caller might save
    straight to disk). `success_suffix` is appended to the "Done." message
    so each caller can say what happens next without the dialog needing to
    know about forms or disk writes.
    """

    def __init__(
        self,
        config: Config,
        on_result: Callable[[CalibrationResult], None] | None = None,
        success_suffix: str = "",
    ) -> None:
        self.config = config
        self._on_result = on_result
        self._success_suffix = success_suffix
        self._cancel = threading.Event()
        self._render_token = 0

    def cancel(self) -> None:
        """Stop any calibration currently in progress.

        Called by a caller that is about to open another instance of this
        dialog, so a still-running recording from a previous one does not
        keep the microphone open underneath the new one -- two streams on
        one device is exactly the conflict this app has to avoid.
        """
        self._cancel.set()

    def show(self, master: tk.Misc) -> None:
        dialog = tk.Toplevel(master)
        dialog.title("Recalibrate")
        theme.apply(dialog)
        dialog.configure(bg=theme.INK)

        # Come to the front once, without staying pinned there. A window that
        # silently opened behind a still-showing overlay looked exactly like a
        # window that never opened at all.
        dialog.lift()
        dialog.attributes("-topmost", True)
        dialog.after(200, lambda: dialog.attributes("-topmost", False))

        dialog.geometry("420x300")
        appicon.set_window_icon(dialog)

        self._cancel.set()
        self._render_token += 1
        token = self._render_token
        self._cancel.clear()

        # The mark itself does the job here (see docs/BRAND.md: "the
        # waveform reacts to the recording level") -- it is redrawn from the
        # live mic level during each sample, not animated on a timer. Starts
        # at its quiet/resting size; update_mark (below) moves it once
        # recording is under way. master= keeps this PhotoImage bound to
        # this dialog's own interpreter (see tests/test_tk_variables.py).
        mark_photo = ImageTk.PhotoImage(
            brand.draw_mark_at_level(MARK_SIZE, 0.0), master=dialog
        )
        mark_label = tk.Label(dialog, image=mark_photo, bg=theme.INK)
        mark_label.image = mark_photo
        mark_label.pack(pady=(16, 4))

        def update_mark(level_dbfs: float) -> None:
            level = meter_from_dbfs(level_dbfs) / 100
            photo = ImageTk.PhotoImage(
                brand.draw_mark_at_level(MARK_SIZE, level), master=dialog
            )
            mark_label.configure(image=photo)
            # Tk keeps no reference of its own; without this the image is
            # collected and the label reverts to blank the moment this
            # function returns (the same gotcha appicon.py and overlay.py
            # already have to work around).
            mark_label.image = photo

        instructions = tk.Label(
            dialog,
            text="Three short recordings. Press Start, then follow the prompt.",
            justify="left",
            anchor="w",
            wraplength=380,
            bg=theme.INK,
            fg=theme.TEXT,
        )
        instructions.pack(fill="x", padx=16, pady=(4, 8))

        progress = ttk.Progressbar(dialog, maximum=1.0)
        progress.pack(fill="x", padx=16, pady=8)

        result_label = tk.Label(
            dialog, text="", justify="left", anchor="w", bg=theme.INK, fg=theme.TEXT_DIM
        )
        result_label.pack(fill="x", padx=16, pady=8)

        def ui(fn) -> None:
            def apply() -> None:
                if self._render_token == token:
                    fn()

            dialog.after(0, apply)

        def stop_on_close() -> None:
            self._cancel.set()
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", stop_on_close)

        def run_calibration() -> None:
            source = MicSource(self.config.device_name, self.config.device_hostapi)
            if not source.open():
                ui(
                    lambda: result_label.configure(
                        text="Could not open the microphone."
                    )
                )
                return

            samples = CalibrationSamples()
            try:
                for name, prompt in (
                    ("quiet", "Be quiet..."),
                    ("speech", "Now talk normally..."),
                    ("yell", "Now yell once!"),
                ):
                    if self._cancel.is_set():
                        return
                    ui(lambda p=prompt: instructions.configure(text=p))
                    frames = SAMPLE_SECONDS[name] * FRAMES_PER_SECOND
                    levels = collect_sample(
                        source,
                        frames,
                        on_progress=lambda f: ui(
                            lambda f=f: progress.configure(value=f)
                        ),
                        is_cancelled=self._cancel.is_set,
                        on_level=lambda lvl: ui(lambda lvl=lvl: update_mark(lvl)),
                    )
                    if self._cancel.is_set():
                        return
                    setattr(samples, name, levels)
            finally:
                source.close()

            result = compute_thresholds(samples)

            def apply_result() -> None:
                if self._on_result is not None:
                    self._on_result(result)
                message = (
                    f"Done. Threshold set to {result.spike_threshold_dbfs} dBFS."
                    + self._success_suffix
                    if result.usable
                    else "That yell was not louder than your speaking voice. "
                    "A safe threshold was used -- press Start to try again."
                )
                result_label.configure(text=message)
                instructions.configure(
                    text="Press Start to redo, or close this window."
                )

            ui(apply_result)

        ttk.Button(
            dialog,
            text="Start",
            style="Accent.TButton",
            command=lambda: threading.Thread(
                target=run_calibration, daemon=True
            ).start(),
        ).pack(pady=8)
