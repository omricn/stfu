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
from datetime import datetime

from stfu.actions import ActionRegistry
from stfu.assets import seed_user_data
from stfu.audio import MicSource, list_input_devices
from stfu.config import config_path, data_dir, load_config, save_config
from stfu.engine import Engine
from stfu.images import ImageLibrary
from stfu.levels import dbfs_from_rms, meter_from_dbfs
from stfu.logstore import LogStore
from stfu.overlay import ClickTracker, DesktopMessage, FourClickOverlay
from stfu.sounds import ClipLibrary, MiniaudioPlayer, SoundBite
from stfu.winapi import RealWinApi


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


def build_real_actions(config) -> ActionRegistry:
    """The live action registry: real windows, real sound, real Win32."""
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
        overlay_factory=lambda: FourClickOverlay(
            ClickTracker(config.overlay_clicks_required),
            "Volume check",
            pictures.pick(),
        ),
        message_factory=lambda: DesktopMessage(
            "Too loud", config.desktop_message_seconds, pictures.pick()
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

    engine = Engine(
        config=config,
        source=source,
        actions=build_real_actions(config) if args.real else PrintingActions(),
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
        engine.stop()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="stfu")
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
