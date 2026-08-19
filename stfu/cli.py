"""Headless entry point: run the engine against the real microphone.

    python -m stfu.cli devices
    python -m stfu.cli pin "Microphone (HyperX Cloud II)" "Windows WASAPI"
    python -m stfu.cli monitor

This exists so detection can be tuned against the actual headset before any UI
is built. Actions are printed, not performed.
"""

from __future__ import annotations

import argparse
import sys
import time
import tkinter as tk
from datetime import datetime

from stfu.actions import ActionRegistry
from stfu.app import create_hidden_root
from stfu.assets import seed_user_data
from stfu.audio import MicSource, list_input_devices
from stfu.config import config_path, data_dir, load_config, save_config
from stfu.detector import TriggerEvent
from stfu.engine import Engine
from stfu.images import ImageLibrary
from stfu.levels import dbfs_from_rms, meter_from_dbfs
from stfu.logstore import LogStore
from stfu.overlay import (
    DESKTOP_MESSAGE,
    OVERLAY_MESSAGE,
    ClickTracker,
    DesktopMessage,
    FourClickOverlay,
)
from stfu.sounds import ClipLibrary, MiniaudioPlayer, SoundBite
from stfu.strikes import ACTION_DESKTOP_DROP, ACTION_OVERLAY
from stfu.winapi import RealWinApi

DEMO_WAIT_SECONDS = 5.0


class PrintingActions:
    """Stand-in for the real actions until Plan 2 builds them."""

    def fire(self, name, event):
        print(
            f"  >>> ACTION {name}  level={event.level_dbfs:.1f} dBFS  "
            f"threshold={event.threshold_dbfs:.1f} dBFS"
        )
        return None


def cmd_devices(_args) -> int:
    for device in list_input_devices():
        print(f"[{device.index}] {device.name}  |  {device.hostapi}")
    return 0


def cmd_pin(args) -> int:
    config = load_config()
    config.device_name = args.name
    config.device_hostapi = args.hostapi
    save_config(config)
    print(f"Pinned '{args.name}' ({args.hostapi})")
    print(f"Written to {config_path()}")
    return 0


class _WaitingWindow:
    """Adapts a real window so this CLI's synchronous frame loop still blocks
    until it is dismissed, the way it always has.

    There is no bridge or second thread here -- `cmd_monitor` reads frames
    and dispatches actions on the same, single thread -- so the window
    classes' own non-blocking show() (see overlay.py) needs something to wait
    on. `root.wait_window()` is the same supported mechanism app.py's PIN
    prompt uses to block without a nested mainloop().
    """

    def __init__(self, root: tk.Misc, window) -> None:
        self._root = root
        self._window = window

    def show(self) -> None:
        top = self._window.show()
        self._root.wait_window(top)


def build_real_actions(config, root: tk.Misc) -> ActionRegistry:
    """The live action registry: real windows, real sound, real Win32.

    `root` is the one hidden Tk root `cmd_monitor` creates for `--real` (see
    create_hidden_root() in app.py) -- every window here is a Toplevel of it.
    """
    sounds_root = data_dir() / "sounds"
    for rung in ("first", "repeat"):
        (sounds_root / rung).mkdir(parents=True, exist_ok=True)

    # So `monitor --real` works out of the box for testing, without having
    # gone through the first-run wizard's seeding step.
    seed_user_data(data_dir())

    pictures = ImageLibrary(data_dir() / "images")

    return ActionRegistry(
        config=config,
        winapi=RealWinApi(),
        sound=SoundBite(
            ClipLibrary(sounds_root),
            MiniaudioPlayer(),
            gain=config.sound_gain,
            max_seconds=config.max_clip_seconds,
        ),
        overlay_factory=lambda: _WaitingWindow(
            root,
            FourClickOverlay(
                root,
                ClickTracker(config.overlay_clicks_required),
                OVERLAY_MESSAGE,
                pictures.pick(),
            ),
        ),
        message_factory=lambda: _WaitingWindow(
            root,
            DesktopMessage(
                root, DESKTOP_MESSAGE, config.desktop_message_seconds, pictures.pick()
            ),
        ),
    )


def cmd_monitor(args) -> int:
    config = load_config()
    if not config.device_name:
        print("No device pinned. Run 'devices' then 'pin'.", file=sys.stderr)
        return 2

    source = MicSource(config.device_name, config.device_hostapi)
    if not source.open():
        print(f"Device not found: {config.device_name}", file=sys.stderr)
        return 2

    # Only --real ever opens a window, and this is the only place in the CLI
    # path that needs a Tk root to make one a Toplevel of -- there is no App
    # instance here to own one, so this asks app.py for the same hidden root
    # it would build itself (see create_hidden_root()'s docstring).
    root = create_hidden_root() if args.real else None

    engine = Engine(
        config=config,
        source=source,
        actions=build_real_actions(config, root) if args.real else PrintingActions(),
        logstore=LogStore(data_dir() / "events.jsonl"),
    )

    print(f"Listening on '{config.device_name}'. Ctrl+C to stop.")
    print(f"Mode={config.threshold_mode}  threshold={config.spike_threshold_dbfs} dBFS")

    start = time.monotonic()
    last_print = 0.0
    try:
        for rms in source.frames():
            mono = time.monotonic() - start
            engine.handle_frame(rms, mono=mono, wall=datetime.now())
            if args.meter and mono - last_print >= 0.25:
                level = dbfs_from_rms(rms)
                bar = "#" * (meter_from_dbfs(level) // 2)
                print(f"\r{level:7.1f} dBFS |{bar:<50}|", end="", flush=True)
                last_print = mono
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        source.close()
        if root is not None:
            root.destroy()
        engine.stop()
    return 0


def cmd_demo(args) -> int:
    """Fire one real trigger with no microphone involved, for screen recording.

    Not a user-facing feature -- see the README's developer section, which is
    the only place this is documented. Hidden from `--help` (see main(), which
    registers it with `help=argparse.SUPPRESS`) so it stays out of the way of
    the CLI surface someone tuning detection actually needs.

    Waits `--wait` seconds (default DEMO_WAIT_SECONDS) so the operator can
    start recording and switch to a normal-looking desktop, then dispatches
    through the real ActionRegistry built by build_real_actions() -- the same
    overlay/message windows, the same sound, the same Win+D -- exactly as a
    genuine yell would, just without needing anyone to actually yell on cue.
    `--desktop-drop` fires the fullscreen message instead of the 4-click
    overlay, so both beats can be recorded separately.
    """
    config = load_config()
    root = create_hidden_root()
    actions = build_real_actions(config, root)

    action_name = ACTION_DESKTOP_DROP if args.desktop_drop else ACTION_OVERLAY
    print(f"stfu demo: firing {action_name} in {args.wait:.0f}s -- start recording now.")
    try:
        time.sleep(args.wait)
    except KeyboardInterrupt:
        print("\ncancelled")
        root.destroy()
        return 0

    event = TriggerEvent(
        kind="spike",
        level_dbfs=-4.0,
        threshold_dbfs=config.spike_threshold_dbfs,
        at=time.monotonic(),
    )
    # Blocks until the window is dismissed: build_real_actions() wraps each
    # window in _WaitingWindow, the same root.wait_window() convention
    # `monitor --real` already relies on (see _WaitingWindow's docstring).
    actions.fire(action_name, event)

    root.destroy()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="stfu")
    subparsers = parser.add_subparsers(
        dest="command", required=True, metavar="{devices,pin,monitor}"
    )

    subparsers.add_parser("devices", help="list input devices").set_defaults(
        func=cmd_devices
    )

    pin = subparsers.add_parser("pin", help="pin the capture device")
    pin.add_argument("name")
    pin.add_argument("hostapi")
    pin.set_defaults(func=cmd_pin)

    monitor = subparsers.add_parser("monitor", help="run detection headlessly")
    monitor.add_argument("--meter", action="store_true", help="show a live level bar")
    monitor.add_argument(
        "--real", action="store_true", help="perform real actions, not just print them"
    )
    monitor.set_defaults(func=cmd_monitor)

    # Undocumented recording aid -- see cmd_demo()'s docstring. help=SUPPRESS
    # alone still prints a literal "==SUPPRESS==" line in --help's subcommand
    # list under this Python's argparse, so the pseudo-action it creates is
    # dropped from subparsers._choices_actions below too -- that list is only
    # ever read by the help formatter; subparsers.choices (which parse_args
    # actually dispatches through) is untouched, so `stfu demo ...` still
    # works, it just never appears in `stfu --help`.
    # Hidden from the top-level listing -- it is a recording aid, not a
    # feature -- but its own flags are documented, because someone who has
    # found the command still needs to discover --desktop-drop.
    demo = subparsers.add_parser(
        "demo",
        help=argparse.SUPPRESS,
        description="Fire a real trigger on a timer, for screen recording.",
    )
    demo.add_argument(
        "--wait",
        type=float,
        default=DEMO_WAIT_SECONDS,
        help=f"seconds before firing (default {DEMO_WAIT_SECONDS:g})",
    )
    demo.add_argument(
        "--desktop-drop",
        action="store_true",
        help="fire the fullscreen message instead of the 4-click overlay",
    )
    demo.set_defaults(func=cmd_demo)
    subparsers._choices_actions = [
        a for a in subparsers._choices_actions if a.dest != "demo"
    ]

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
