"""Wiring, lifecycle, and device watch: turns the engine into an app.

Three threads want attention here -- Tk (main), audio capture, and pystray --
and actions.fire() must block the capture thread until a window it opened is
dismissed, because the engine uses the return value to suppress detection.
uibridge.py resolves that; this module assembles the pieces around it and
owns the order everything starts and stops in.

Two things below exist only because of hard-won, empirically confirmed
findings about nesting independent Tk() windows inside this hidden root's
event loop -- every window class in this project (the overlay, the desktop
message, the report, settings, the PIN prompt) builds its own `tk.Tk()` and
calls `.mainloop()` on it, and that mainloop() runs *nested* inside this
module's pump loop whenever it is reached through the bridge:

1. `_pump` reschedules its own next call *before* draining the bridge queue.
   If the hidden root has no pending timer at the moment a queued request
   opens one of those nested windows, the nested mainloop() can hang forever
   instead of returning once its own window closes -- confirmed by direct
   reproduction, not a guess. Keeping a timer always pending avoids it.

2. Shutdown ends the hidden root with `destroy()`, never `quit()`. `quit()`
   sets a flag shared by every mainloop() call on this thread, and it is
   consumed by whichever one is currently innermost -- which, if a window
   opened through the bridge happens to be showing when Exit is pressed, is
   that window's loop, not this root's. The app would hang, having quietly
   closed the wrong loop. `destroy()` is scoped to this widget and unwinds
   this root's mainloop() correctly regardless of what is nested inside it.
"""

from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from datetime import datetime
from typing import Callable

from stfu import autostart
from stfu.actions import ActionRegistry
from stfu.assets import seed_user_data
from stfu.audio import MicSource
from stfu.calibrationui import CalibrationDialog
from stfu.config import Config, data_dir, load_config, save_config
from stfu.engine import Engine
from stfu.firstrun import needs_setup
from stfu.firstrunui import FirstRunWizard
from stfu.images import ImageLibrary
from stfu.instance import SingleInstance
from stfu.logstore import LogStore
from stfu.overlay import ClickTracker, DesktopMessage, FourClickOverlay
from stfu.reportui import ReportWindow
from stfu.settingsui import SettingsWindow
from stfu.sounds import RUNG_FIRST, RUNG_REPEAT, ClipLibrary, MiniaudioPlayer, SoundBite
from stfu.tray import STATE_LISTENING, STATE_NO_MIC, STATE_PAUSED, Tray
from stfu.uibridge import UiBridge
from stfu.winapi import RealWinApi

log = logging.getLogger(__name__)

PUMP_INTERVAL_MS = 50
MIC_POLL_SECONDS = 5.0
# ~0.5s at the 20ms frame size -- often enough to notice a vanished device
# quickly, rare enough that querying every input device on every frame would
# be wasteful.
AVAILABILITY_CHECK_FRAMES = 25
PAUSE_MINUTES = 15
SHUTDOWN_JOIN_TIMEOUT_S = 5.0


class DeviceWatch:
    """Tracks whether the pinned microphone is present, and how long to wait
    before checking again while it is absent.

    Two separate concerns on purpose. `update` records a transition given a
    fresh presence reading and is safe to call any time the caller has one;
    `should_poll` only answers whether it is time to go get a fresh reading at
    all -- checking on every 20ms audio frame would mean repeatedly querying
    every input device on the system for no reason.
    """

    def __init__(self, poll_seconds: float) -> None:
        self.poll_seconds = poll_seconds
        self.present = True
        self._last_poll = 0.0

    def update(self, present: bool, now: float) -> str | None:
        """Record a presence reading. Returns "lost", "found", or None if
        nothing changed since the last call."""
        self._last_poll = now
        if present == self.present:
            return None
        self.present = present
        return "found" if present else "lost"

    def should_poll(self, now: float) -> bool:
        """True once `poll_seconds` have elapsed since the last `update`."""
        return now - self._last_poll >= self.poll_seconds


class _BridgedWindow:
    """Adapts a zero-arg window factory so its show() runs on the Tk thread
    and blocks the caller until the window is dismissed.

    actions.fire() runs on the capture thread and must block until the window
    it opened closes -- the engine uses the return value to decide how long to
    suppress detection. bridge.submit() is exactly that: it enqueues the
    work, blocks, and returns once the main thread has run it.
    """

    def __init__(self, bridge: UiBridge, factory: Callable[[], object]) -> None:
        self._bridge = bridge
        self._factory = factory

    def show(self) -> None:
        self._bridge.submit(lambda: self._factory().show())


def _ensure_sound_dirs(sounds_root) -> None:
    for rung in (RUNG_FIRST, RUNG_REPEAT):
        (sounds_root / rung).mkdir(parents=True, exist_ok=True)


def _build_actions(config: Config, bridge: UiBridge) -> ActionRegistry:
    """The live action registry: real windows (marshalled through the
    bridge), real sound, real Win32."""
    sounds_root = data_dir() / "sounds"
    _ensure_sound_dirs(sounds_root)

    sound = SoundBite(
        ClipLibrary(sounds_root),
        MiniaudioPlayer(),
        gain=config.sound_gain,
        max_seconds=config.max_clip_seconds,
    )

    pictures = ImageLibrary(data_dir() / "images")

    return ActionRegistry(
        config=config,
        winapi=RealWinApi(),
        sound=sound,
        overlay_factory=lambda: _BridgedWindow(
            bridge,
            lambda: FourClickOverlay(
                ClickTracker(config.overlay_clicks_required),
                "Volume check",
                pictures.pick(),
            ),
        ),
        message_factory=lambda: _BridgedWindow(
            bridge,
            lambda: DesktopMessage(
                "Too loud", config.desktop_message_seconds, pictures.pick()
            ),
        ),
    )


def _apply_autostart(config: Config) -> None:
    """Reconcile the HKCU Run entry with the saved config, every launch --
    never assumed from whether the wizard just ran."""
    if config.autostart:
        autostart.enable(autostart.executable_path())
    else:
        autostart.disable()


class App:
    """Wires the engine to real hardware and windows, and owns the lifecycle
    of the capture and tray threads plus the hidden Tk root this object's
    run() occupies."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.bridge = UiBridge()
        self.logstore = LogStore(data_dir() / "events.jsonl")
        self.actions = _build_actions(config, self.bridge)
        self.source = MicSource(config.device_name, config.device_hostapi)
        self.engine = Engine(config, self.source, self.actions, self.logstore)

        self._capture_stop = threading.Event()
        self._mic_present = threading.Event()
        self._mic_present.set()

        self.tray = Tray(
            config,
            self.bridge,
            on_report=self._open_report,
            on_settings=self._open_settings,
            on_recalibrate=self._open_recalibrate,
            on_pause=self._pause,
            on_exit=self._request_exit,
        )

        self.root: tk.Tk | None = None
        self._capture_thread: threading.Thread | None = None
        self._tray_thread: threading.Thread | None = None

    def run(self) -> int:
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name="stfu-capture", daemon=True
        )
        self._capture_thread.start()

        self._tray_thread = threading.Thread(
            target=self.tray.run, name="stfu-tray", daemon=True
        )
        self._tray_thread.start()

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.after(PUMP_INTERVAL_MS, self._pump)
        self.root.mainloop()

        # mainloop() only returns once the hidden root has been destroyed
        # (see _request_exit). From here nothing is nested inside a
        # Tk-dispatched callback, so it is safe to block briefly joining the
        # other threads.
        self.engine.stop()
        self._capture_stop.set()
        self.source.close()
        # Must happen before joining the capture thread. If it is currently
        # blocked inside actions.fire() -> bridge.submit(), waiting for a
        # window to be pumped, nothing will ever pump it again once the Tk
        # root is gone -- only shutdown() releases a caller already waiting
        # in submit(). Joining first, without this, would deadlock.
        self.bridge.shutdown()
        self._capture_thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT_S)
        if self._capture_thread.is_alive():
            log.warning("capture thread did not stop within %ss", SHUTDOWN_JOIN_TIMEOUT_S)

        self.tray.stop()
        self._tray_thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT_S)
        if self._tray_thread.is_alive():
            log.warning("tray thread did not stop within %ss", SHUTDOWN_JOIN_TIMEOUT_S)

        return 0

    def _pump(self) -> None:
        # Reschedule before draining the queue -- see the module docstring.
        if self.root is not None:
            self.root.after(PUMP_INTERVAL_MS, self._pump)
        self.bridge.pump_once()

    # --- capture thread ----------------------------------------------------

    def _capture_loop(self) -> None:
        """Feeds the engine from the microphone, and survives it vanishing.

        MicSource.frames() blocks until close(); it does not raise or exit on
        its own just because the device was unplugged mid-stream, so presence
        is checked periodically rather than inferred from an exception.
        """
        start = time.monotonic()

        def elapsed() -> float:
            return time.monotonic() - start

        watch = DeviceWatch(poll_seconds=MIC_POLL_SECONDS)
        is_open = self.source.open()
        if not is_open:
            watch.update(present=False, now=elapsed())
            self._mic_lost()

        while not self._capture_stop.is_set():
            if not is_open:
                if watch.should_poll(elapsed()):
                    is_open = self.source.open()
                    if watch.update(present=is_open, now=elapsed()) == "found":
                        self._mic_found()
                else:
                    self._capture_stop.wait(timeout=0.2)
                continue

            frame_count = 0
            for rms in self.source.frames():
                if self._capture_stop.is_set():
                    break
                self.engine.handle_frame(rms, mono=elapsed(), wall=datetime.now())
                frame_count += 1
                if (
                    frame_count % AVAILABILITY_CHECK_FRAMES == 0
                    and not self.source.available
                ):
                    break

            if self._capture_stop.is_set():
                break

            # frames() only stops on our own break above -- otherwise it
            # blocks until close(). Either the availability check just fired,
            # or the stream simply stopped delivering when the device
            # vanished between two checks; either way, the device is gone.
            self.source.close()
            is_open = False
            watch.update(present=False, now=elapsed())
            self._mic_lost()

    def _mic_lost(self) -> None:
        self._mic_present.clear()
        self.engine.on_mic_lost()
        self.tray.set_state(STATE_NO_MIC)

    def _mic_found(self) -> None:
        self._mic_present.set()
        self.engine.on_mic_found()
        self.tray.set_state(STATE_PAUSED if self.engine.paused else STATE_LISTENING)

    # --- tray actions --------------------------------------------------
    # Tray already dispatches these through the bridge (see tray.py), so by
    # the time any of these run they are on the Tk thread and may open a
    # window directly.

    def _open_report(self) -> None:
        ReportWindow(self.logstore).show()

    def _open_settings(self) -> None:
        SettingsWindow(self.config).show()

    def _open_recalibrate(self) -> None:
        # The tray shortcut opens the calibration flow directly (F3) rather
        # than detouring through the whole settings window. There is no form
        # here to hold the result pending a Save, so a successful run is
        # written straight to disk and to the live config the engine already
        # holds a reference to -- the next frame's threshold check picks it
        # up immediately.
        def apply_result(result) -> None:
            self.config.spike_threshold_dbfs = result.spike_threshold_dbfs
            self.config.sustain_threshold_dbfs = result.sustain_threshold_dbfs
            save_config(self.config)

        CalibrationDialog(
            self.config, on_result=apply_result, success_suffix=" Saved."
        ).show()

    def _pause(self) -> None:
        self.engine.pause()
        self.tray.set_state(STATE_PAUSED)
        timer = threading.Timer(PAUSE_MINUTES * 60, self._auto_resume)
        timer.daemon = True
        timer.start()

    def _auto_resume(self) -> None:
        self.engine.resume()
        self.tray.set_state(
            STATE_LISTENING if self._mic_present.is_set() else STATE_NO_MIC
        )

    def _request_exit(self) -> None:
        """Starts shutdown and ends mainloop(); the rest of the teardown
        happens in run(), after mainloop() returns -- see the module
        docstring for why this calls destroy() and not quit()."""
        if self.root is not None:
            self.root.destroy()


def main() -> int:
    instance = SingleInstance()
    if not instance.acquire():
        log.info("another instance is already running; exiting")
        return 0

    try:
        config = load_config()
        if needs_setup(config):
            result = FirstRunWizard(config).run()
            if result is None:
                log.info("first-run setup was cancelled; exiting without saving")
                return 0
            config = result
            save_config(config)

            seeded = seed_user_data(data_dir())
            log.info("seeded %d default clips and pictures", seeded)

        _apply_autostart(config)

        return App(config).run()
    finally:
        instance.release()
