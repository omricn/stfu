"""The first-run setup wizard.

Renders FirstRunFlow. All the rules live in the flow; this only draws them and
collects answers.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import ttk

from stfu.audio import MicSource, list_input_devices
from stfu.calibration import CalibrationSamples, collect_sample, compute_thresholds
from stfu.config import SAMPLE_RATE, Config, data_dir, save_config
from stfu.firstrun import FirstRunFlow

log = logging.getLogger(__name__)

SAMPLE_SECONDS = {"quiet": 10, "speech": 10, "yell": 5}
FRAMES_PER_SECOND = 50

TITLES = {
    "welcome": "S.TFU",
    "device": "Which microphone?",
    "calibrate": "Let's measure your voice",
    "test": "Try it",
    "pin": "Set a PIN",
    "sounds": "Sound bites",
    "autostart": "Start with Windows?",
}

BODIES = {
    "welcome": (
        "This app listens to your microphone and reacts when you yell.\n\n"
        "It is not hidden. There is a tray icon, and it will tell you every "
        "time it does something.\n\n"
        "Setup takes about a minute."
    ),
    "sounds": (
        "Sound bites play when the app reacts.\n\n"
        "Drop .wav, .mp3, .ogg or .flac files into the folders below. You can "
        "do this now or any time later -- new clips are picked up without "
        "restarting.\n\n"
        "first\\   plays on the first yell of a session\n"
        "repeat\\  plays on every later one"
    ),
}


class FirstRunWizard:
    """One window whose body is replaced as the flow advances."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.flow = FirstRunFlow()
        self.root: tk.Tk | None = None
        self._body: tk.Frame | None = None
        self._status = None
        self._next = None
        self._cancelled = False
        self._render_token = 0
        self._cancel = threading.Event()

    def run(self) -> Config | None:
        """Show the wizard. Returns the finished Config, or None if abandoned."""
        self.root = tk.Tk()
        self.root.title("S.TFU setup")
        self.root.geometry("640x460")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._body = tk.Frame(self.root)
        self._body.pack(fill="both", expand=True, padx=24, pady=16)

        controls = tk.Frame(self.root)
        controls.pack(fill="x", padx=24, pady=12)
        tk.Button(controls, text="Back", command=self._on_back).pack(side="left")
        self._next = tk.Button(controls, text="Next", command=self._on_next)
        self._next.pack(side="right")

        self._render()
        self.root.mainloop()

        if self._cancelled:
            return None
        return self.flow.to_config(self.config)

    def _on_close(self) -> None:
        self._cancelled = True
        if self.root:
            self.root.destroy()

    def _on_back(self) -> None:
        if self.flow.back():
            self._render()

    def _on_next(self) -> None:
        if not self.flow.can_advance():
            return
        if not self.flow.advance():
            if self.root:
                self.root.destroy()
            return
        self._render()

    def _clear(self) -> None:
        for child in list(self._body.winfo_children()):
            child.destroy()

    def _render(self) -> None:
        # Any background work from the previous step must stop before its
        # widgets are destroyed -- Back during calibration otherwise leaves a
        # daemon thread writing to a progress bar that no longer exists.
        self._cancel.set()
        self._render_token += 1
        self._clear()
        step = self.flow.current
        tk.Label(
            self._body, text=TITLES[step], font=("Segoe UI", 20, "bold"), anchor="w"
        ).pack(fill="x", pady=(0, 12))

        renderer = getattr(self, f"_render_{step}", None)
        if renderer is not None:
            renderer()
        else:
            tk.Label(
                self._body,
                text=BODIES.get(step, ""),
                justify="left",
                anchor="w",
                wraplength=560,
            ).pack(fill="x")

        self._refresh_next()

    def _refresh_next(self) -> None:
        if self._next is not None:
            self._next.configure(
                state="normal" if self.flow.can_advance() else "disabled"
            )

    def _ui(self, token: int, fn) -> None:
        """Run a widget update on the Tk thread, skipping it if the step it
        belongs to has already been replaced.

        Cross-thread Tcl calls happen to work -- CPython marshals them onto the
        mainloop thread -- right up until the widget has been destroyed, at
        which point they raise on a thread whose traceback nobody sees.
        """
        root = self.root
        if root is None:
            return

        def apply() -> None:
            if self._render_token == token:
                fn()

        root.after(0, apply)

    # --- steps that need more than a paragraph -------------------------------

    def _render_device(self) -> None:
        tk.Label(
            self._body,
            text="Pick the microphone you actually use, then check the meter moves "
            "when you speak.",
            justify="left",
            anchor="w",
            wraplength=560,
        ).pack(fill="x", pady=(0, 8))

        devices = list_input_devices()
        listbox = tk.Listbox(self._body, height=10)
        for device in devices:
            listbox.insert("end", f"{device.name}  |  {device.hostapi}")
        listbox.pack(fill="both", expand=True)

        def choose(_event=None) -> None:
            selection = listbox.curselection()
            if not selection:
                return
            device = devices[selection[0]]
            self.flow.record(
                device_name=device.name, device_hostapi=device.hostapi
            )
            self._refresh_next()

        listbox.bind("<<ListboxSelect>>", choose)

    def _render_calibrate(self) -> None:
        instructions = tk.Label(
            self._body,
            text="Three short recordings. Press Start, then follow the prompt.",
            justify="left",
            anchor="w",
            wraplength=560,
        )
        instructions.pack(fill="x", pady=(0, 8))

        progress = ttk.Progressbar(self._body, maximum=1.0)
        progress.pack(fill="x", pady=8)

        result_label = tk.Label(self._body, text="", justify="left", anchor="w")
        result_label.pack(fill="x", pady=8)

        def run_calibration() -> None:
            token = self._render_token
            self._cancel.clear()

            source = MicSource(
                self.flow.answers.get("device_name", ""),
                self.flow.answers.get("device_hostapi", ""),
            )
            if not source.open():
                self._ui(
                    token,
                    lambda: result_label.configure(
                        text="Could not open that microphone."
                    ),
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
                    self._ui(token, lambda p=prompt: instructions.configure(text=p))
                    frames = SAMPLE_SECONDS[name] * FRAMES_PER_SECOND
                    levels = collect_sample(
                        source,
                        frames,
                        on_progress=lambda f: self._ui(
                            token, lambda f=f: progress.configure(value=f)
                        ),
                        is_cancelled=self._cancel.is_set,
                    )
                    if self._cancel.is_set():
                        return
                    setattr(samples, name, levels)
            finally:
                source.close()

            result = compute_thresholds(samples)
            self.flow.record(
                spike_threshold_dbfs=result.spike_threshold_dbfs,
                sustain_threshold_dbfs=result.sustain_threshold_dbfs,
            )
            message = (
                f"Done. Threshold set to {result.spike_threshold_dbfs} dBFS."
                if result.usable
                else "That yell was not louder than your speaking voice. "
                "A safe threshold was used -- press Start to try again."
            )
            self._ui(token, lambda: result_label.configure(text=message))
            self._ui(
                token,
                lambda: instructions.configure(
                    text="Press Start to redo, or Next to continue."
                ),
            )
            self._ui(token, self._refresh_next)

        tk.Button(
            self._body,
            text="Start",
            command=lambda: threading.Thread(
                target=run_calibration, daemon=True
            ).start(),
        ).pack()

    def _render_pin(self) -> None:
        tk.Label(
            self._body,
            text="The PIN is needed to change settings or close the app.\n"
            "It is a speed bump, not a lock.",
            justify="left",
            anchor="w",
            wraplength=560,
        ).pack(fill="x", pady=(0, 8))

        first = tk.Entry(self._body, show="*", width=20)
        second = tk.Entry(self._body, show="*", width=20)
        note = tk.Label(self._body, text="", anchor="w")

        tk.Label(self._body, text="PIN", anchor="w").pack(fill="x")
        first.pack(anchor="w", pady=(0, 8))
        tk.Label(self._body, text="Confirm", anchor="w").pack(fill="x")
        second.pack(anchor="w")
        note.pack(fill="x", pady=8)

        def check(_event=None) -> None:
            a, b = first.get(), second.get()
            if a and a == b:
                self.flow.record(pin=a)
                note.configure(text="PIN set.")
            else:
                self.flow.answers.pop("pin", None)
                note.configure(text="" if not b else "The two entries differ.")
            self._refresh_next()

        first.bind("<KeyRelease>", check)
        second.bind("<KeyRelease>", check)

    def _render_sounds(self) -> None:
        sounds_root = data_dir() / "sounds"
        for rung in ("first", "repeat"):
            (sounds_root / rung).mkdir(parents=True, exist_ok=True)

        tk.Label(
            self._body,
            text=BODIES["sounds"],
            justify="left",
            anchor="w",
            wraplength=560,
        ).pack(fill="x")
        tk.Label(self._body, text=str(sounds_root), anchor="w", fg="#555555").pack(
            fill="x", pady=8
        )

        def open_folder() -> None:
            import os

            os.startfile(sounds_root)  # noqa: S606 - opening a known local folder

        tk.Button(self._body, text="Open the folder", command=open_folder).pack(
            anchor="w"
        )

    def _render_autostart(self) -> None:
        # Default on, but only on the first visit. Re-rendering must not
        # overwrite a choice the user already made and then navigated away from.
        current = bool(self.flow.answers.get("autostart", True))
        variable = tk.BooleanVar(value=current)
        self.flow.record(autostart=current)

        def toggle() -> None:
            self.flow.record(autostart=bool(variable.get()))

        tk.Checkbutton(
            self._body,
            text="Start S.TFU when Windows starts",
            variable=variable,
            command=toggle,
        ).pack(anchor="w")
        tk.Label(
            self._body,
            text="\nThat is everything. Press Next to finish.",
            justify="left",
            anchor="w",
        ).pack(fill="x")

    def _render_test(self) -> None:
        tk.Label(
            self._body,
            text="You can test it properly once setup finishes -- the tray icon "
            "has a live meter.\n\nPress Next to carry on.",
            justify="left",
            anchor="w",
            wraplength=560,
        ).pack(fill="x")
