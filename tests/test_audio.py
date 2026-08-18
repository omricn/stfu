import pytest

from stfu.audio import FakeSource, InputDevice, find_device


DEVICES = [
    InputDevice(index=1, name="Microphone (HyperX Cloud II)", hostapi="Windows WASAPI"),
    InputDevice(index=2, name="Microphone (Realtek Audio)", hostapi="MME"),
    InputDevice(index=3, name="Microphone (HyperX Cloud II)", hostapi="MME"),
]


def test_finds_the_device_matching_name_and_hostapi():
    found = find_device("Microphone (HyperX Cloud II)", "Windows WASAPI", DEVICES)
    assert found.index == 1


def test_name_match_is_exact_not_fuzzy():
    assert find_device("HyperX", "Windows WASAPI", DEVICES) is None


def test_returns_none_when_the_device_is_absent():
    assert find_device("Microphone (Missing)", "Windows WASAPI", DEVICES) is None


def test_falls_back_to_a_name_match_on_any_hostapi():
    found = find_device("Microphone (HyperX Cloud II)", "Nonexistent API", DEVICES)
    assert found.index == 1


def test_returns_none_when_nothing_is_configured():
    assert find_device("", "", DEVICES) is None


def test_fake_source_yields_the_frames_it_was_given():
    source = FakeSource([0.1, 0.2, 0.3])
    assert list(source.frames()) == [0.1, 0.2, 0.3]


def test_fake_source_reports_available_by_default():
    assert FakeSource([0.1]).available is True


def test_fake_source_can_simulate_an_absent_device():
    source = FakeSource([], available=False)
    assert source.available is False
    assert list(source.frames()) == []
