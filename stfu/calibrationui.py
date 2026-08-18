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

from stfu.audio import MicSource
from stfu.calibration import (
    CalibrationResult,
    CalibrationSamples,
    collect_sample,
    compute_thresholds,
)
from stfu.config import Config

SAMPLE_SECONDS = {"quiet": 10, "speech": 10, "yell": 5}
FRAMES_PER_SECOND = 50


class CalibrationDialog:
    """Runs the three-sample calibration flow in a small window.

    `show()` with no arguments opens its own top-level window and blocks the
    caller until it is closed -- the same pattern every other window in this
    project follows (see app.py's module docstring on nested mainloop()s).
    Pass `master=` to embed it as a Toplevel of an already-running window
    instead; then `show()` returns immediately and the dialog floats
    alongside its parent, exactly as it did when this was a method on
    SettingsWindow.

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

    def show(self, master: tk.Misc | None = None) -> None:
        owns_loop = master is None
        dialog = tk.Tk() if owns_loop else tk.Toplevel(master)
        dialog.title("Recalibrate")
        dialog.geometry("420x220")

        self._cancel.set()
        self._render_token += 1
        token = self._render_token
        self._cancel.clear()

        instructions = tk.Label(
            dialog,
            text="Three short recordings. Press Start, then follow the prompt.",
            justify="left",
            anchor="w",
            wraplength=380,
        )
        instructions.pack(fill="x", padx=16, pady=(16, 8))

        progress = ttk.Progressbar(dialog, maximum=1.0)
        progress.pack(fill="x", padx=16, pady=8)

        result_label = tk.Label(dialog, text="", justify="left", anchor="w")
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

        tk.Button(
            dialog,
            text="Start",
            command=lambda: threading.Thread(
                target=run_calibration, daemon=True
            ).start(),
        ).pack(pady=8)

        if owns_loop:
            dialog.mainloop()
