import random

import pytest

from stfu.actions import ActionRegistry
from stfu.config import Config
from stfu.detector import TriggerEvent
from stfu.sounds import ClipLibrary, FakePlayer, SoundBite
from stfu.strikes import ACTION_DESKTOP_DROP, ACTION_OVERLAY
from stfu.winapi import FakeWinApi


class FakeWindow:
    def __init__(self, log, name):
        self._log = log
        self._name = name

    def show(self):
        self._log.append(self._name)


@pytest.fixture
def parts(tmp_path):
    shown = []
    winapi = FakeWinApi()
    library = ClipLibrary(tmp_path, rng=random.Random(0))
    bite = SoundBite(library, FakePlayer(duration=2.0), gain=1.0, max_seconds=15)
    registry = ActionRegistry(
        config=Config(),
        winapi=winapi,
        sound=bite,
        overlay_factory=lambda: FakeWindow(shown, "overlay"),
        message_factory=lambda: FakeWindow(shown, "message"),
    )
    return registry, winapi, bite, shown


def event():
    return TriggerEvent("spike", -6.0, -12.0, 1.23)


def make_clip(tmp_path, rung, name="a.wav"):
    folder = tmp_path / rung
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"not really audio")


def test_the_overlay_action_minimises_before_showing(parts):
    registry, winapi, _, shown = parts
    registry.fire(ACTION_OVERLAY, event())
    assert winapi.calls == ["minimize_foreground"]
    assert shown == ["overlay"]


def test_the_desktop_action_shows_the_desktop_then_the_message(parts):
    registry, winapi, _, shown = parts
    registry.fire(ACTION_DESKTOP_DROP, event())
    assert winapi.calls == ["show_desktop"]
    assert shown == ["message"]


def test_the_overlay_action_plays_a_first_rung_clip(parts, tmp_path):
    registry, _, bite, _ = parts
    make_clip(tmp_path, "first")
    registry.fire(ACTION_OVERLAY, event())
    assert bite.player.played[0][0].parent.name == "first"


def test_the_desktop_action_plays_a_repeat_rung_clip(parts, tmp_path):
    registry, _, bite, _ = parts
    make_clip(tmp_path, "repeat")
    registry.fire(ACTION_DESKTOP_DROP, event())
    assert bite.player.played[0][0].parent.name == "repeat"


def test_the_clip_duration_is_returned_to_the_engine(parts, tmp_path):
    registry, _, _, _ = parts
    make_clip(tmp_path, "first")
    assert registry.fire(ACTION_OVERLAY, event()) == 2.0


def test_no_clip_returns_none_so_nothing_is_suppressed(parts):
    registry, _, _, _ = parts
    assert registry.fire(ACTION_OVERLAY, event()) is None


def test_an_unknown_action_name_is_survivable(parts):
    registry, winapi, _, shown = parts
    assert registry.fire("teleport_the_pc", event()) is None
    assert winapi.calls == []
    assert shown == []


def test_the_usb_light_action_is_registered_but_does_nothing(parts):
    registry, _, _, shown = parts
    assert registry.fire("usb_light", event()) is None
    assert shown == []


def test_the_overlay_action_minimises_then_sounds_then_shows(tmp_path):
    # Both orderings are load-bearing. show() blocks until the overlay is
    # dismissed, so a clip started after it would not play until the user had
    # already clicked through; and a window shown before the minimise would be
    # hidden behind a fullscreen game. Three separate logs cannot prove this,
    # so everything records into one.
    order = []
    make_clip(tmp_path, "first")

    class OrderedWinApi:
        def minimize_foreground(self):
            order.append("minimize")
            return True

        def show_desktop(self):
            order.append("desktop")

    class OrderedPlayer:
        def play(self, path, gain, max_seconds):
            order.append("sound")
            return 2.0

        def stop(self):
            pass

    registry = ActionRegistry(
        config=Config(),
        winapi=OrderedWinApi(),
        sound=SoundBite(
            ClipLibrary(tmp_path, rng=random.Random(0)), OrderedPlayer(), 1.0, 15
        ),
        overlay_factory=lambda: FakeWindow(order, "overlay"),
        message_factory=lambda: FakeWindow(order, "message"),
    )
    registry.fire(ACTION_OVERLAY, event())
    assert order == ["minimize", "sound", "overlay"]


def test_the_desktop_action_drops_then_sounds_then_shows(tmp_path):
    order = []
    make_clip(tmp_path, "repeat")

    class OrderedWinApi:
        def minimize_foreground(self):
            order.append("minimize")
            return True

        def show_desktop(self):
            order.append("desktop")

    class OrderedPlayer:
        def play(self, path, gain, max_seconds):
            order.append("sound")
            return 2.0

        def stop(self):
            pass

    registry = ActionRegistry(
        config=Config(),
        winapi=OrderedWinApi(),
        sound=SoundBite(
            ClipLibrary(tmp_path, rng=random.Random(0)), OrderedPlayer(), 1.0, 15
        ),
        overlay_factory=lambda: FakeWindow(order, "overlay"),
        message_factory=lambda: FakeWindow(order, "message"),
    )
    registry.fire(ACTION_DESKTOP_DROP, event())
    assert order == ["desktop", "sound", "message"]
