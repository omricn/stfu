"""Regression test: a device that enumerates is not a device that opens.

Setup could not be completed at all because the chosen microphone was a
WDM-KS entry, and opening it raised:

    sounddevice.PortAudioError: Error starting stream: Unanticipated host
    error [PaErrorCode -9999]: 'WdmSyncIoctl: DeviceIoControl ...'

MicSource.open() let that escape, killing the calibration thread. The same
physical microphone was reachable through WASAPI the whole time.
"""

from stfu.audio import InputDevice, candidate_devices

HEADSET = "Headset (Baseus Bowie WM02)"

DEVICES = [
    InputDevice(index=1, name=HEADSET, hostapi="MME"),
    InputDevice(index=7, name=HEADSET, hostapi="Windows DirectSound"),
    InputDevice(index=15, name=HEADSET, hostapi="Windows WASAPI"),
    InputDevice(index=20, name="Microphone (Realtek USB Audio)", hostapi="Windows WDM-KS"),
]


def test_it_returns_every_host_api_for_a_device():
    assert len(candidate_devices(HEADSET, "Windows WASAPI", DEVICES)) == 3


def test_the_pinned_pairing_is_tried_first():
    found = candidate_devices(HEADSET, "MME", DEVICES)
    assert found[0].hostapi == "MME"


def test_the_rest_follow_in_preference_order():
    found = candidate_devices(HEADSET, "MME", DEVICES)
    assert [d.hostapi for d in found[1:]] == ["Windows WASAPI", "Windows DirectSound"]


def test_a_missing_pinned_host_api_still_yields_the_others():
    # The pinned pairing has gone -- a driver change, a different port -- but
    # the microphone is still there under other host APIs.
    found = candidate_devices(HEADSET, "Nonexistent API", DEVICES)
    assert [d.hostapi for d in found] == [
        "Windows WASAPI",
        "Windows DirectSound",
        "MME",
    ]


def test_a_wdmks_only_device_is_still_offered():
    # Some devices enumerate under WDM-KS alone. Excluding that host API
    # outright would hide them entirely, so it stays -- last.
    found = candidate_devices("Microphone (Realtek USB Audio)", "Windows WDM-KS", DEVICES)
    assert len(found) == 1
    assert found[0].hostapi == "Windows WDM-KS"


def test_an_unknown_device_yields_nothing():
    assert candidate_devices("Microphone (Unplugged)", "MME", DEVICES) == []


def test_an_empty_name_yields_nothing():
    assert candidate_devices("", "", DEVICES) == []
