"""The first-run setup wizard.

Renders FirstRunFlow. All the rules live in the flow; this only draws them and
collects answers.

This is the one other sanctioned owner of a `tk.Tk()` besides app.py (see
app.py's module docstring and tests/test_single_tk_root.py) -- it runs
before that root exists and is destroyed before it is created. It is also,
by the same token, the one screen in this app that cannot simply call
`theme.apply()` on someone else's root: it builds and owns its own.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from stfu import appicon, brand, theme
from stfu.audio import MicSource, list_input_devices, preferred_input_devices
from stfu.calibration import CalibrationSamples, collect_sample, compute_thresholds
from stfu.config import SAMPLE_RATE, Config, data_dir, save_config
from stfu.firstrun import STEPS, FirstRunFlow

log = logging.getLogger(__name__)

_UI_PUMP_MS = 50  # how often the main thread drains queued UI work

SAMPLE_SECONDS = {"quiet": 10, "speech": 10, "yell": 5}
FRAMES_PER_SECOND = 50

MARK_SIZE = 56
DOT_SIZE = 8
DOT_GAP = 14

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


def _guarded(fn):
    """Wrap a thread body so a crash is logged instead of vanishing.

    threading.excepthook writes to stderr, which a windowed exe does not have.
    A calibration thread that died on its first line therefore looked exactly
    like a Start button that did nothing.
    """

    def run() -> None:
        try:
            fn()
        except Exception:
            log.exception("the calibration thread failed")

    return run


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
        self._ui_queue: queue.Queue = queue.Queue()
        self._pump_id = None
        self._mark_photo: ImageTk.PhotoImage | None = None
        self._dots: list[int] = []
        self._dots_canvas: tk.Canvas | None = None

    def run(self) -> Config | None:
        """Show the wizard. Returns the finished Config, or None if abandoned."""
        self.root = tk.Tk()
        appicon.set_window_icon(self.root)
        theme.apply(self.root)
        self.root.configure(bg=theme.INK)
        self.root.title("S.TFU setup")
        self.root.geometry("640x480")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Drains work queued by the calibration thread. Started here rather
        # than per-step so no step can forget it and appear to hang.
        self._pump_ui()

        header = tk.Frame(self.root, bg=theme.INK)
        header.pack(fill="x", padx=24, pady=(20, 4))

        # Built once and kept for the wizard's whole life, not per-render --
        # the mark never changes between steps, and master= keeps this
        # PhotoImage bound to this window's own interpreter (see
        # tests/test_tk_variables.py).
        mark_image = brand.draw_mark(MARK_SIZE)
        self._mark_photo = ImageTk.PhotoImage(mark_image, master=self.root)
        tk.Label(header, image=self._mark_photo, bg=theme.INK).pack()

        self._dots_canvas = tk.Canvas(
            header,
            height=DOT_SIZE + 4,
            bg=theme.INK,
            highlightthickness=0,
        )
        self._dots_canvas.pack(pady=(10, 0))
        self._build_dots()

        self._body = tk.Frame(self.root, bg=theme.INK)
        self._body.pack(fill="both", expand=True, padx=24, pady=16)

        controls = tk.Frame(self.root, bg=theme.INK)
        controls.pack(fill="x", padx=24, pady=(0, 20))
        ttk.Button(controls, text="Back", command=self._on_back).pack(side="left")
        self._next = ttk.Button(
            controls, text="Next", command=self._on_next, style="Accent.TButton"
        )
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

    # --- the tri-colour step dots ------------------------------------------

    def _build_dots(self) -> None:
        """One dot per step, evenly spaced. Coloured by the step's position
        in the flow (early = indigo, mid = amber, late = red -- the same
        accent order the meter and report use), filled once passed, hollow
        ahead -- so progress reads at a glance without a caption."""
        canvas = self._dots_canvas
        count = len(STEPS)
        width = count * DOT_GAP
        canvas.configure(width=width)
        self._dots = []
        for index in range(count):
            x = index * DOT_GAP + DOT_GAP / 2
            dot = canvas.create_oval(
                x - DOT_SIZE / 2,
                2,
                x + DOT_SIZE / 2,
                2 + DOT_SIZE,
                outline=theme.HAIRLINE,
                width=1,
            )
            self._dots.append(dot)

    def _refresh_dots(self) -> None:
        canvas = self._dots_canvas
        if canvas is None:
            return
        current = self.flow.index
        count = len(STEPS)
        for index, dot in enumerate(self._dots):
            fraction = index / max(1, count - 1)
            colour = (
                theme.RED
                if fraction > 0.66
                else theme.AMBER
                if fraction > 0.33
                else theme.INDIGO
            )
            if index <= current:
                canvas.itemconfigure(dot, fill=colour, outline=colour)
            else:
                canvas.itemconfigure(dot, fill=theme.INK, outline=theme.HAIRLINE)

    def _render(self) -> None:
        # Any background work from the previous step must stop before its
        # widgets are destroyed -- Back during calibration otherwise leaves a
        # daemon thread writing to a progress bar that no longer exists.
        self._cancel.set()
        self._render_token += 1
        self._clear()
        self._refresh_dots()
        step = self.flow.current
        tk.Label(
            self._body,
            text=TITLES[step],
            font=theme.FONT_TITLE,
            bg=theme.INK,
            fg=theme.TEXT,
            anchor="w",
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
                bg=theme.INK,
                fg=theme.TEXT,
                font=theme.FONT_BODY,
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
        # NOT root.after(). Tk's after() calls createcommand, which raises
        # "main thread is not in main loop" when called off the main thread --
        # so the very helper meant to make cross-thread updates safe killed the
        # calibration thread on its first call, silently, and Start appeared to
        # do nothing. Queue it instead and let the main thread drain it, which
        # is what uibridge.py does for the rest of the app.
        self._ui_queue.put((token, fn))

    def _pump_ui(self) -> None:
        """Drain queued UI work. Runs on the main thread, on a Tk timer."""
        root = self.root
        if root is None:
            return
        while True:
            try:
                token, fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            if token != self._render_token:
                continue  # its step has already been replaced
            try:
                fn()
            except Exception:
                log.exception("a queued wizard update failed")
        self._pump_id = root.after(_UI_PUMP_MS, self._pump_ui)

    def _label(self, text: str, **kwargs) -> tk.Label:
        """A body label pre-filled with the dark theme's colours -- classic
        tk.Label ignores ttk styles entirely, so every one of these needs its
        own bg/fg (see theme.py's module docstring)."""
        opts = dict(
            justify="left",
            anchor="w",
            bg=theme.INK,
            fg=theme.TEXT,
            font=theme.FONT_BODY,
        )
        opts.update(kwargs)
        return tk.Label(self._body, text=text, **opts)

    # --- steps that need more than a paragraph -------------------------------

    def _render_device(self) -> None:
        self._label(
            "Pick the microphone you actually use, then check the meter moves "
            "when you speak.",
            wraplength=560,
        ).pack(fill="x", pady=(0, 8))

        # The raw list has one entry per host API per device -- 19 entries
        # for about 5 physical devices on a typical machine, several of them
        # not microphones at all. Filtered down for the wizard; the full list
        # stays available via `stfu.cli devices` for anyone whose device the
        # filter hid.
        devices = preferred_input_devices(list_input_devices())
        # Listbox has no ttk equivalent and ignores ttk styles entirely --
        # it is coloured directly, the same way every classic tk widget here
        # has to be (see theme.py's module docstring).
        listbox = tk.Listbox(
            self._body,
            height=10,
            bg=theme.SURFACE,
            fg=theme.TEXT,
            selectbackground=theme.INDIGO,
            selectforeground=theme.TEXT,
            highlightthickness=1,
            highlightbackground=theme.HAIRLINE,
            highlightcolor=theme.INDIGO,
            borderwidth=0,
        )
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
        instructions = self._label(
            "Three short recordings. Press Start, then follow the prompt.",
            wraplength=560,
        )
        instructions.pack(fill="x", pady=(0, 8))

        progress = ttk.Progressbar(self._body, maximum=1.0)
        progress.pack(fill="x", pady=8)

        result_label = self._label("")
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
                        text="Could not open that microphone.\n"
                        "Press Back and choose a different one -- some devices "
                        "are listed by Windows but refuse to open, or are held "
                        "by another program."
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

        ttk.Button(
            self._body,
            text="Start",
            command=lambda: threading.Thread(
                target=_guarded(run_calibration), daemon=True
            ).start(),
        ).pack()

    def _render_pin(self) -> None:
        self._label(
            "The PIN is needed to change settings or close the app.\n"
            "It is a speed bump, not a lock.",
            wraplength=560,
        ).pack(fill="x", pady=(0, 8))

        first_var = tk.StringVar(master=self.root, value="")
        second_var = tk.StringVar(master=self.root, value="")
        first = ttk.Entry(self._body, textvariable=first_var, show="*", width=20)
        second = ttk.Entry(self._body, textvariable=second_var, show="*", width=20)
        note = self._label("", fg=theme.RED)

        self._label("PIN").pack(fill="x")
        first.pack(anchor="w", pady=(0, 8))
        self._label("Confirm").pack(fill="x")
        second.pack(anchor="w")
        note.pack(fill="x", pady=8)

        def check(_event=None) -> None:
            a, b = first_var.get(), second_var.get()
            if a and a == b:
                self.flow.record(pin=a)
                note.configure(text="PIN set.", fg=theme.TEXT_DIM)
            else:
                self.flow.answers.pop("pin", None)
                note.configure(
                    text="" if not b else "The two entries differ.", fg=theme.RED
                )
            self._refresh_next()

        first.bind("<KeyRelease>", check)
        second.bind("<KeyRelease>", check)

    def _render_sounds(self) -> None:
        sounds_root = data_dir() / "sounds"
        for rung in ("first", "repeat"):
            (sounds_root / rung).mkdir(parents=True, exist_ok=True)

        self._label(BODIES["sounds"], wraplength=560).pack(fill="x")
        self._label(str(sounds_root), fg=theme.TEXT_DIM).pack(fill="x", pady=8)

        def open_folder() -> None:
            import os

            os.startfile(sounds_root)  # noqa: S606 - opening a known local folder

        ttk.Button(self._body, text="Open the folder", command=open_folder).pack(
            anchor="w"
        )

    def _render_autostart(self) -> None:
        # Default on, but only on the first visit. Re-rendering must not
        # overwrite a choice the user already made and then navigated away from.
        current = bool(self.flow.answers.get("autostart", True))
        variable = tk.BooleanVar(master=self.root, value=current)
        self.flow.record(autostart=current)

        def toggle() -> None:
            self.flow.record(autostart=bool(variable.get()))

        ttk.Checkbutton(
            self._body,
            text="Start S.TFU when Windows starts",
            variable=variable,
            command=toggle,
        ).pack(anchor="w")
        self._label("\nThat is everything. Press Next to finish.").pack(fill="x")

    def _render_test(self) -> None:
        self._label(
            "You can test it properly once setup finishes -- the tray icon "
            "has a live meter.\n\nPress Next to carry on.",
            wraplength=560,
        ).pack(fill="x")
