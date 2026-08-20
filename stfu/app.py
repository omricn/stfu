"""Wiring, lifecycle, and device watch: turns the engine into an app.

Three threads want attention here -- Tk (main), audio capture, and pystray.

**This module owns the only `tk.Tk()` in the running app** (the hidden pump
root below), with one sanctioned exception: `firstrunui.FirstRunWizard`,
which runs before this root exists and is destroyed before it is created.
Every window elsewhere in `stfu/` -- the overlay, the desktop message, the
report, settings, the meter, the calibration dialog, the PIN prompt -- is a
`tk.Toplevel` of this root, not a `Tk()` of its own, and none of them call
`.mainloop()`. `tests/test_single_tk_root.py` enforces this mechanically.

That used to not be true, and it produced five separate field bugs: settings
rendering blank (variables bound to the wrong interpreter), the PIN prompt
opening as a bare untitled window (a PhotoImage bound to the wrong
interpreter, throwing before the dialog finished building), a deadlocked
capture thread, a desktop message whose nested mainloop() never returned (so
the re-entry guard around it never cleared and later strikes played sound
with no window), and a PIN-gated tray item whose window never appeared after
the PIN was accepted. Patching each instance individually never held; only
removing the second interpreter did.

A caller that genuinely needs to block until a window closes (the PIN
prompt's `gate()`, so a menu action does not fire before the PIN is checked)
uses `master.wait_window(toplevel)` -- Tk's supported modal mechanism, which
reliably returns once the window is destroyed and does not share `mainloop()`'s
quit()-flag ambiguity (see point 2 below). Every other window's `show()`
returns as soon as it has built its Toplevel; `_BridgedWindow` below finds out
when it actually closes via the Toplevel's own `<Destroy>` event.

Two more things below are still true with a single interpreter:

1. `_pump` reschedules its own next call *before* draining the bridge queue,
   so the hidden root always has a pending timer. `wait_window()` (used by
   the PIN gate) runs its own nested event-processing loop while it waits,
   and depends on that timer to keep firing during the wait.

2. Shutdown ends the hidden root with `destroy()`, never `quit()`. `quit()`
   sets a flag shared by every mainloop() call on this thread, and with two
   or more `Tk()` instances it would be consumed by whichever mainloop() is
   currently innermost rather than this root's own -- moot now that this is
   the only mainloop() in the process, but `destroy()` is the correct call
   regardless: it is scoped to this widget and unwinds its own mainloop()
   deterministically.
"""

from __future__ import annotations

import atexit
import faulthandler
import io
import logging
import os
import shlex
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from typing import Callable

from stfu import appicon, audio, autostart, sounds
from stfu.actions import ActionRegistry
from stfu.assets import seed_user_data
from stfu.audio import MicSource
from stfu.calibrationui import CalibrationDialog
from stfu.config import (
    Config,
    config_path,
    data_dir,
    load_config,
    reset_config,
    save_config,
)
from stfu.engine import Engine
from stfu.firstrun import needs_setup
from stfu.firstrunui import FirstRunWizard
from stfu.images import ImageLibrary
from stfu.instance import SingleInstance
from stfu.levels import dbfs_from_rms
from stfu.logstore import LogStore
from stfu.meter import MeterState
from stfu.meterui import MeterWindow
from stfu.overlay import (
    DESKTOP_MESSAGE,
    OVERLAY_MESSAGE,
    ClickTracker,
    DesktopMessage,
    FourClickOverlay,
)
from stfu import pinprompt
from stfu.reportui import ReportWindow
from stfu.settingsui import SettingsWindow
from stfu.sounds import RUNG_FIRST, RUNG_REPEAT, ClipLibrary, MiniaudioPlayer, SoundBite
from stfu.splashui import SplashWindow
from stfu.tray import (
    STATE_LISTENING,
    STATE_NO_MIC,
    STATE_PAUSED,
    STATE_SCHEDULED_OFF,
    Tray,
    preload_image_codecs,
)
from stfu.uibridge import UiBridge
from stfu.winapi import RealWinApi

log = logging.getLogger(__name__)

FIRST_LAUNCH_NOTICE_DELAY_MS = 3000
PUMP_INTERVAL_MS = 50
MIC_POLL_SECONDS = 5.0
# ~0.5s at the 20ms frame size -- often enough to notice a vanished device
# quickly, rare enough that querying every input device on every frame would
# be wasteful.
AVAILABILITY_CHECK_FRAMES = 25
PAUSE_MINUTES = 15
SHUTDOWN_JOIN_TIMEOUT_S = 5.0
# How long a fresh process will retry for the single-instance mutex before
# giving up -- see SingleInstance.acquire()'s docstring for the two races
# this covers (the "Start over" relaunch, and a plain manual relaunch right
# after closing the app). Generous relative to SHUTDOWN_JOIN_TIMEOUT_S * 2,
# the worst-case time this process's own teardown can take.
INSTANCE_ACQUIRE_RETRY_SECONDS = 12.0


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
    """Adapts a zero-arg window factory so its show() runs on the Tk thread,
    without blocking the caller.

    It used to block, via bridge.submit(), on the theory that actions.fire()
    should not return until the window it opened had closed. That was wrong,
    and it deadlocked the app in the field: fire() runs on the *capture*
    thread, so blocking it stops audio being read at all. The overlay waits
    for four clicks and the fullscreen message for ten seconds -- during which
    nothing was detected -- and if either window failed to close for any
    reason, detection was dead permanently. Real logs showed exactly one
    trigger per session, then silence.

    Nothing actually needed the block. The engine's suppression window comes
    from the sound clip's duration, which ActionRegistry already obtains
    before the window is opened.

    A window still showing is not reopened: two overlays stacked on each other
    would be worse than one, and the cooldown means it can only happen when
    something has already gone wrong.

    The re-entry guard used to be cleared in a `finally` around the window's
    own `mainloop()`, which only ran once that call returned. Now that
    `show()` on the window classes themselves returns immediately (see
    overlay.py), there is no call to hang a `finally` off any more -- so the
    guard is cleared by the Toplevel's own `<Destroy>` event instead, which
    fires exactly once, whenever and however the window actually closes. A
    guard that can only be set and never guaranteed to clear is worse than no
    guard at all (that was bug #4: a desktop message's nested mainloop() never
    returned, so this flag latched on and silently ate strikes 3 and 4). If
    the window fails to even build, the `except` below clears it directly,
    since no Toplevel -- and so no `<Destroy>` event -- ever existed.
    """

    def __init__(self, bridge: UiBridge, factory: Callable[[], object]) -> None:
        self._bridge = bridge
        self._factory = factory
        self._open = threading.Event()

    def show(self) -> None:
        if self._open.is_set():
            log.warning("a window is already open; not opening another")
            return
        self._open.set()

        def run() -> None:
            try:
                top = self._factory().show()
            except Exception:
                log.exception("failed to build/show window")
                self._open.clear()
                return
            top.bind("<Destroy>", lambda _e: self._open.clear(), add="+")

        self._bridge.submit_async(run)


def _ensure_sound_dirs(sounds_root) -> None:
    for rung in (RUNG_FIRST, RUNG_REPEAT):
        (sounds_root / rung).mkdir(parents=True, exist_ok=True)


def _build_actions(
    config: Config, bridge: UiBridge, get_master: Callable[[], tk.Misc]
) -> ActionRegistry:
    """The live action registry: real windows (marshalled through the
    bridge), real sound, real Win32.

    `get_master` is called lazily, once per trigger, not eagerly here -- this
    runs during App.__init__, before App.run() has created the hidden Tk
    root these windows must be a Toplevel of. By the time a trigger actually
    calls it, the bridge has already dispatched onto the Tk thread and the
    root is guaranteed to exist.
    """
    sounds_root = data_dir() / "sounds"
    _ensure_sound_dirs(sounds_root)

    sound = SoundBite(
        ClipLibrary(sounds_root),
        MiniaudioPlayer(),
        gain=config.sound_gain,
        max_seconds=config.max_clip_seconds,
    )

    pictures = ImageLibrary(data_dir() / "images")

    overlay_window = _BridgedWindow(
        bridge,
        lambda: FourClickOverlay(
            get_master(),
            ClickTracker(config.overlay_clicks_required),
            OVERLAY_MESSAGE,
            pictures.pick(),
        ),
    )
    message_window = _BridgedWindow(
        bridge,
        lambda: DesktopMessage(
            get_master(),
            DESKTOP_MESSAGE,
            config.desktop_message_seconds,
            pictures.pick(),
        ),
    )

    return ActionRegistry(
        config=config,
        winapi=RealWinApi(),
        sound=sound,
        # Built once each, not per trigger: the "already open" flag lives on
        # these objects and would be useless if a fresh one appeared each time.
        overlay_factory=lambda: overlay_window,
        message_factory=lambda: message_window,
    )


def _apply_autostart(config: Config) -> None:
    """Reconcile the HKCU Run entry with the saved config, every launch --
    never assumed from whether the wizard just ran."""
    if config.autostart:
        autostart.enable(autostart.executable_path())
    else:
        autostart.disable()


def _relaunch_process() -> None:
    """Start a brand-new S.TFU process, frozen or not.

    Reuses autostart.executable_path() rather than a second copy of the same
    frozen/unfrozen distinction: frozen, it is the exe's own path and needs
    no further parsing; unfrozen, it is `"<python>" -m stfu` as one quoted
    string (built for the registry's Run key, which wants exactly that), so
    it is shlex.split() here to get an argv Popen can execute directly.
    """
    command = autostart.executable_path()
    args = [command] if getattr(sys, "frozen", False) else shlex.split(command)

    creationflags = 0
    if sys.platform == "win32":
        # Detach: the child must outlive this process, which is about to exit.
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )

    subprocess.Popen(
        args,
        env=_child_environment(os.environ),
        close_fds=True,
        creationflags=creationflags,
    )


# PyInstaller records where a one-file build unpacked itself. Names have
# changed across versions, so match the prefix as well as the older exact name.
_PYINSTALLER_ENV_PREFIX = "_PYI"
_PYINSTALLER_ENV_NAMES = frozenset({"_MEIPASS2"})


def _child_environment(env) -> dict:
    """The current environment with PyInstaller's bootstrap variables removed.

    A frozen one-file build unpacks itself into a temp _MEI directory and
    records that path in the environment. A child that inherits those looks
    for its runtime in the *parent's* directory -- which the parent deletes
    as it exits, so the child dies with "Can't find a usable init.tcl"
    before it can draw anything. Stripping them makes the child unpack its
    own copy, which is what a relaunch needs.
    """
    return {
        key: value
        for key, value in env.items()
        if not key.startswith(_PYINSTALLER_ENV_PREFIX)
        and key not in _PYINSTALLER_ENV_NAMES
    }


def perform_start_over(
    spawn: Callable[[], None],
    reset: Callable[[], None],
    request_exit: Callable[[], None],
) -> bool:
    """Orchestrates Settings' "Start over": relaunch first, wipe state
    second, exit third -- in that order deliberately.

    A relaunch that fails to even start must leave this process running
    with its state untouched, not exit into nothing with no process left at
    all -- that is the one way this feature could brick the app. Trying the
    relaunch before touching anything means a failure here is a no-op: the
    `except` below returns False without calling `reset` or `request_exit`,
    so the running app is unaffected and the operator can see it and try
    again.

    Once the relaunch has actually started, `reset` runs and then
    `request_exit` while this process is still alive -- the new process
    will retry the single-instance mutex until this one's own teardown
    releases it (see SingleInstance.acquire()), so by the time the new
    process gets far enough to call load_config(), the config this process
    just deleted is already gone.

    A plain function, not a method, so it can be unit-tested with fake
    `spawn`/`reset`/`request_exit` callables without a real Tk root, a real
    subprocess, or a real config file (see tests/test_app_wiring.py).
    """
    try:
        spawn()
    except Exception:
        log.exception("could not relaunch for Start over; keeping this process running")
        return False
    reset()
    request_exit()
    return True


def create_hidden_root() -> tk.Tk:
    """The one `tk.Tk()` this module constructs.

    Used by `App.run()` for the real app, and by `stfu.cli`'s
    `monitor --real`, which has no App instance of its own but still needs
    exactly one root for its windows to be a Toplevel of -- rather than have
    cli.py construct a second `tk.Tk()` call site, it asks this module for
    one, keeping the construction itself in exactly one place (see
    tests/test_single_tk_root.py).
    """
    root = tk.Tk()
    appicon.set_window_icon(root)
    root.withdraw()
    return root


def _show_splash_before_wizard() -> None:
    """Show the launch splash ahead of first-run setup, on a throwaway
    hidden root built and fully torn down before anything else runs.

    On every *other* launch the splash is layered on top of the real app,
    already running (see `App.run()`) -- there is nothing to layer it on top
    of here, since setup has not produced a Config the engine could run
    with yet. So this blocks instead, via `wait_window`, until the splash
    closes itself, and then destroys this root completely before
    `FirstRunWizard` constructs its own separate `Tk()` -- this module's
    invariant is "at most one Tk() alive at a time", not "app.py's hidden
    root always outlives everything else" (see the module docstring), and a
    root built and destroyed entirely within this one function, before the
    wizard's root exists, never overlaps with it.

    Wrapped so any failure here -- a missing/corrupt gif, a Tk quirk -- is
    logged and skipped rather than delaying setup by so much as a frame;
    the splash is decoration, first-run setup is the job.
    """
    try:
        root = create_hidden_root()
    except Exception:
        log.exception("could not create a root for the launch splash; skipping it")
        return

    try:
        top = SplashWindow(root).show()
        if top is not None:
            root.wait_window(top)
    except Exception:
        log.exception("launch splash failed before setup; skipping it")
    finally:
        root.destroy()


class App:
    """Wires the engine to real hardware and windows, and owns the lifecycle
    of the capture and tray threads plus the hidden Tk root this object's
    run() occupies."""

    def __init__(self, config: Config, *, just_set_up: bool = False) -> None:
        self.config = config
        self._just_set_up = just_set_up
        self.bridge = UiBridge()
        self.logstore = LogStore(data_dir() / "events.jsonl")
        # Windows are not built with a master here -- run() has not created
        # the hidden root yet. get_master() is read lazily by _build_actions'
        # factories and by the tray's gate, once each is actually invoked
        # (always after run() has assigned self.root; see _build_actions).
        self.root: tk.Tk | None = None
        self.actions = _build_actions(config, self.bridge, lambda: self.root)
        self.source = MicSource(config.device_name, config.device_hostapi)
        self.engine = Engine(config, self.source, self.actions, self.logstore)
        self.meter = MeterState()

        self._capture_stop = threading.Event()
        self._mic_present = threading.Event()
        self._mic_present.set()
        # Last scheduled-off value pushed to the tray. The schedule changes
        # state on a clock boundary with no event to hang a callback on, so the
        # frame loop notices it -- but set_state rebuilds the icon bitmap, and
        # the frame loop runs ~50 times a second.
        self._tray_scheduled_off = False

        self.tray = Tray(
            config,
            self.bridge,
            on_report=self._open_report,
            on_settings=self._open_settings,
            on_recalibrate=self._open_recalibrate,
            on_meter=self._open_meter,
            on_pause=self._pause,
            on_exit=self._request_exit,
            gate=lambda: pinprompt.gate(self.config, self.root),
        )

        self._capture_thread: threading.Thread | None = None
        self._tray_thread: threading.Thread | None = None

    def run(self) -> int:
        # Before any thread exists: both of these pull modules out of the
        # PyInstaller archive on first use, and doing that off the main
        # thread is what killed the process right after first-run setup.
        audio.preload()
        sounds.preload()
        preload_image_codecs()

        self._capture_thread = threading.Thread(
            target=self._capture_loop, name="stfu-capture", daemon=True
        )
        self._capture_thread.start()

        self._tray_thread = threading.Thread(
            target=self.tray.run, name="stfu-tray", daemon=True
        )
        self._tray_thread.start()

        self.root = create_hidden_root()

        # Shown *after* the two threads above are already running, as an
        # overlay on top of an app that does not need it to finish anything
        # -- see splashui.py's module docstring. show() is the same
        # non-blocking convention every other window here uses: it returns
        # once the Toplevel exists, and animates itself out via its own
        # after() ticks once mainloop() below starts pumping them. Wrapped
        # here too, on top of show()'s own internal guard, because a failure
        # this close to the real event loop starting is exactly the kind
        # that must never be allowed to stop it from starting.
        try:
            SplashWindow(self.root).show()
        except Exception:
            log.exception("could not show the launch splash; continuing without it")

        self.root.after(PUMP_INTERVAL_MS, self._pump)
        if self._just_set_up:
            # Delayed, not immediate: pystray files the icon with the shell
            # from its own thread, and a notification raised before that has
            # happened is dropped.
            self.root.after(FIRST_LAUNCH_NOTICE_DELAY_MS, self._announce_running)
        log.info("entering the main event loop")
        self.root.mainloop()
        log.info("the main event loop returned; shutting down")

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

    def _announce_running(self) -> None:
        """Tell the user the app is up, right after first-run setup.

        Setup finished, the splash played, and the user reported that the app
        "did not open" -- it had, and was listening the whole time. There is
        no main window by design, and Windows had tucked the new tray icon
        behind the overflow chevron, so a healthy start and a crash looked
        identical.
        """
        self.tray.announce(
            "S.TFU is running",
            "Listening in the background. Find me in the tray -- click the "
            "^ arrow by the clock if you cannot see the icon.",
        )

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
                now = elapsed()
                self.engine.handle_frame(rms, mono=now, wall=datetime.now())
                self._update_meter(rms, now, mic_present=True)
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

    def _update_meter(self, rms: float, now: float, mic_present: bool) -> None:
        """Feed the live meter window (F5) from the frame the capture thread
        already has -- never a second stream. See stfu/meterui.py for how the
        Tk side reads this without adding cross-thread traffic."""
        scheduled_off = self.engine.scheduled_off
        self.meter.update(
            dbfs=dbfs_from_rms(rms),
            threshold_dbfs=self.engine.detector.current_threshold(),
            cooldown_remaining_s=self.engine.detector.cooldown_remaining(now),
            mic_present=mic_present,
            scheduled_off=scheduled_off,
        )

        # Only on a change: see __init__'s note on the cached value.
        if scheduled_off != self._tray_scheduled_off:
            self._tray_scheduled_off = scheduled_off
            # A manual pause outranks the schedule in the icon, the same way it
            # outranks it in the engine's gate -- don't overwrite amber-paused
            # with amber-scheduled and lose the tooltip that says which.
            if not self.engine.paused:
                self.tray.set_state(self._listening_state(mic_present))

    def _listening_state(self, mic_present: bool) -> str:
        """The tray state for an app that is not manually paused.

        Missing microphone first: that is a fault, and it must never be hidden
        behind a state that says everything is fine on purpose.
        """
        if not mic_present:
            return STATE_NO_MIC
        if self.engine.scheduled_off:
            return STATE_SCHEDULED_OFF
        return STATE_LISTENING

    def _mic_lost(self) -> None:
        self._mic_present.clear()
        self.engine.on_mic_lost()
        self.tray.set_state(STATE_NO_MIC)
        self.meter.update(
            dbfs=dbfs_from_rms(0.0),
            threshold_dbfs=self.engine.detector.current_threshold(),
            cooldown_remaining_s=0.0,
            mic_present=False,
        )

    def _mic_found(self) -> None:
        self._mic_present.set()
        self.engine.on_mic_found()
        # Resync the cache as well as the icon. _update_meter compares
        # against it to decide whether the icon needs rebuilding, and a value
        # left over from before the outage would make the next frame see a
        # change that already happened.
        self._tray_scheduled_off = self.engine.scheduled_off
        self.tray.set_state(
            STATE_PAUSED
            if self.engine.paused
            else self._listening_state(mic_present=True)
        )

    # --- tray actions --------------------------------------------------
    # Tray already dispatches these through the bridge (see tray.py), so by
    # the time any of these run they are on the Tk thread and may open a
    # window directly.

    def _open_report(self) -> None:
        ReportWindow(self.root, self.logstore, self.config).show()

    def _open_settings(self) -> None:
        SettingsWindow(self.root, self.config, on_start_over=self._start_over).show()

    def _open_meter(self) -> None:
        # Read-only diagnostics (F5): no PIN, and it reads self.meter rather
        # than touching the engine or the capture thread directly.
        MeterWindow(self.root, self.meter).show()

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
        ).show(self.root)

    def _pause(self) -> None:
        self.engine.pause()
        self.tray.set_state(STATE_PAUSED)
        timer = threading.Timer(PAUSE_MINUTES * 60, self._auto_resume)
        timer.daemon = True
        timer.start()

    def _auto_resume(self) -> None:
        self.engine.resume()
        self.tray.set_state(self._listening_state(self._mic_present.is_set()))

    def _request_exit(self) -> None:
        """Starts shutdown and ends mainloop(); the rest of the teardown
        happens in run(), after mainloop() returns -- see the module
        docstring for why this calls destroy() and not quit()."""
        if self.root is not None:
            self.root.destroy()

    def _start_over(self) -> None:
        """Settings' "Start over": wipe saved state and relaunch fresh into
        first-run setup. See perform_start_over() for the ordering that
        keeps a failed relaunch from bricking the app."""
        perform_start_over(
            spawn=_relaunch_process,
            reset=self._reset_app_state,
            request_exit=self._request_exit,
        )

    def _reset_app_state(self) -> None:
        """Delete the config (the pinned device, the PIN, the calibrated
        thresholds) and the event log -- never the sound clips or pictures
        under data_dir(), which are the user's own files, not app state
        (see settingsui.py's confirmation text, which promises exactly
        this)."""
        reset_config()
        self.logstore.clear()


def _configure_logging() -> None:
    r"""Send this app's own log to %LOCALAPPDATA%\STFU\app.log.

    It was never configured, so every exception the UI bridge and the action
    dispatcher carefully caught and logged went nowhere at all. That is how a
    deadlocked capture thread and a dialog that failed to build both presented
    as "nothing happens" with no way to find out why.
    """
    from logging.handlers import RotatingFileHandler

    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return

    handler = RotatingFileHandler(
        data_dir() / "app.log", maxBytes=512_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    _catch_silent_deaths(handler)


def _catch_silent_deaths(handler: logging.Handler) -> None:
    """Make every way this process can die leave a trace in app.log.

    A windowed exe has no stderr. Python's default hooks write there, so an
    unhandled exception on the main thread, a crash in a worker thread, and a
    native fault inside PortAudio all look identical from the outside: the
    window vanishes and the log simply stops. That is exactly what happened
    after first-run setup -- the last line written was a routine INFO, and
    there was no way to tell whether the interpreter had raised, segfaulted,
    or exited cleanly.

    faulthandler covers the native case (it writes a C-level traceback to the
    same file), the two excepthooks cover the Python cases, and the atexit
    hook distinguishes a clean exit from all of them by leaving a line that
    only an orderly shutdown can produce.
    """
    stream = getattr(handler, "stream", None)
    if stream is not None:
        try:
            faulthandler.enable(file=stream, all_threads=True)
        except (AttributeError, io.UnsupportedOperation, ValueError, OSError):
            # A handler whose stream cannot be given a real file descriptor.
            # The Python-level hooks below are the ones that matter most.
            log.debug("faulthandler could not attach to the log file")

    def on_uncaught(exc_type, exc, tb) -> None:
        log.critical("unhandled exception on the main thread", exc_info=(exc_type, exc, tb))

    def on_thread_uncaught(args) -> None:
        log.critical(
            "unhandled exception in thread %r",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = on_uncaught
    threading.excepthook = on_thread_uncaught
    atexit.register(lambda: log.info("S.TFU exiting normally"))


def _save_setup_result(config: Config) -> None:
    r"""Persist the wizard's answers, and prove on disk that it worked.

    Setup completed, the line logged immediately after this save ran, and yet
    %LOCALAPPDATA%\STFU\config.json still carried the previous day's mtime
    with no .bak beside it -- so the app came back up asking to be set up all
    over again. A bare save_config() call cannot tell you which of those two
    stories is true. Logging the resolved path and the file's size and mtime
    straight after the write does, and it costs one stat().
    """
    path = config_path()
    try:
        save_config(config)
    except OSError:
        log.exception("could not save the setup result to %s", path)
        raise

    try:
        stat = path.stat()
        log.info(
            "saved setup to %s (%d bytes, mtime %s, device %r)",
            path,
            stat.st_size,
            datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            config.device_name,
        )
    except OSError:
        log.error("save_config(%s) returned but the file is not there", path)


def main() -> int:
    _configure_logging()
    log.info("S.TFU starting")
    instance = SingleInstance()
    if not instance.acquire(retry_seconds=INSTANCE_ACQUIRE_RETRY_SECONDS):
        log.info("another instance is already running; exiting")
        return 0

    try:
        did_setup = False
        config = load_config()
        log.info(
            "loaded config from %s (device %r, threshold %s dBFS, setup needed: %s)",
            config_path(),
            config.device_name,
            config.spike_threshold_dbfs,
            needs_setup(config),
        )
        if needs_setup(config):
            # Shown before the wizard's own Tk() exists at all -- see
            # _show_splash_before_wizard's docstring for why this is the one
            # case the splash blocks rather than just layering on top.
            _show_splash_before_wizard()
            result = FirstRunWizard(config).run()
            if result is None:
                log.info("first-run setup was cancelled; exiting without saving")
                return 0
            config = result
            _save_setup_result(config)

            did_setup = True
            seeded = seed_user_data(data_dir())
            log.info("seeded %d default clips and pictures", seeded)

        _apply_autostart(config)

        return App(config, just_set_up=did_setup).run()
    finally:
        instance.release()
