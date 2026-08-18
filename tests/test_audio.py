import pytest

from stfu.audio import (
    FakeSource,
    InputDevice,
    find_device,
    frame_samples_for_rate,
    preferred_input_devices,
)


DEVICES = [
    InputDevice(index=1, name="Microphone (HyperX Cloud II)", hostapi="Windows WASAPI"),
    InputDevice(index=2, name="Microphone (Realtek Audio)", hostapi="MME"),
    InputDevice(index=3, name="Microphone (HyperX Cloud II)", hostapi="MME"),
]

# The 19 devices PortAudio enumerated on the machine that surfaced F2, in
# enumeration order. One headset and one Intel Smart Sound array, each
# repeated once per host API; two host-API aliases that are not capture
# endpoints at all; three raw Bluetooth driver strings; and the MME name for
# the Intel array truncated to PortAudio's 31-character MME limit.
_REAL_MACHINE_DEVICES = [
    InputDevice(0, "Microsoft Sound Mapper - Input", "MME"),
    InputDevice(1, "Headset (Baseus Bowie WM02)", "MME"),
    InputDevice(2, "Microphone Array (Intel® Smart ", "MME"),
    InputDevice(3, "Primary Sound Capture Driver", "Windows DirectSound"),
    InputDevice(4, "Headset (Baseus Bowie WM02)", "Windows DirectSound"),
    InputDevice(
        5,
        "Microphone Array (Intel® Smart Sound Technology for Digital Microphones)",
        "Windows DirectSound",
    ),
    InputDevice(
        6,
        "Microphone Array (Intel® Smart Sound Technology for Digital Microphones)",
        "Windows WASAPI",
    ),
    InputDevice(7, "Headset (Baseus Bowie WM02)", "Windows WASAPI"),
    InputDevice(8, "Stereo Mix (Realtek HD Audio Stereo input)", "Windows WDM-KS"),
    InputDevice(9, "PC Speaker (Realtek HD Audio output with SST)", "Windows WDM-KS"),
    InputDevice(
        10, "PC Speaker (Realtek HD Audio 2nd output with SST)", "Windows WDM-KS"
    ),
    InputDevice(11, "Microphone (Realtek HD Audio Mic input)", "Windows WDM-KS"),
    InputDevice(12, "Microphone Array 1 ()", "Windows WDM-KS"),
    InputDevice(13, "Microphone Array 2 ()", "Windows WDM-KS"),
    InputDevice(
        14,
        r"Input (@System32\drivers\bthhfenum.sys,#2;%1 Hands-Free%0;(Baseus Bowie WM02))",
        "Windows WDM-KS",
    ),
    InputDevice(
        15,
        r"Input (@System32\drivers\btha2dp.sys,#1;%1%0;(Baseus Bowie WM02))",
        "Windows WDM-KS",
    ),
    InputDevice(
        16,
        r"Headset (@System32\drivers\bthhfenum.sys,#2;%1 Hands-Free%0;(Baseus Bowie WM02))",
        "Windows WDM-KS",
    ),
    InputDevice(17, "Microphone (Realtek USB Audio)", "Windows WDM-KS"),
    InputDevice(18, "Microphone (VIAVAD Wave)", "Windows WDM-KS"),
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


# --- preferred_input_devices -------------------------------------------


def test_drops_host_api_aliases_and_non_capture_endpoints():
    filtered = preferred_input_devices(_REAL_MACHINE_DEVICES)
    names = [d.name for d in filtered]
    assert "Microsoft Sound Mapper - Input" not in names
    assert "Primary Sound Capture Driver" not in names
    assert not any(name.startswith("PC Speaker") for name in names)


def test_drops_raw_driver_strings():
    filtered = preferred_input_devices(_REAL_MACHINE_DEVICES)
    assert not any("@System32\\" in d.name for d in filtered)


def test_headset_survives_as_exactly_one_wasapi_entry():
    filtered = preferred_input_devices(_REAL_MACHINE_DEVICES)
    headsets = [d for d in filtered if d.name == "Headset (Baseus Bowie WM02)"]
    assert len(headsets) == 1
    assert headsets[0].hostapi == "Windows WASAPI"
    assert headsets[0].index == 7


def test_mme_truncated_name_merges_with_its_untruncated_sibling():
    """MME truncates to 31 chars, so the Intel Smart Sound array's MME entry
    does not string-match its WASAPI/DirectSound sibling. It must still
    collapse to one entry, not survive as a duplicate."""
    filtered = preferred_input_devices(_REAL_MACHINE_DEVICES)
    intel_entries = [d for d in filtered if d.name.startswith("Microphone Array (Intel")]
    assert len(intel_entries) == 1
    assert intel_entries[0].hostapi == "Windows WASAPI"
    assert (
        intel_entries[0].name
        == "Microphone Array (Intel® Smart Sound Technology for Digital Microphones)"
    )


def test_exact_filtered_list_from_the_real_machine_devices():
    filtered = preferred_input_devices(_REAL_MACHINE_DEVICES)
    assert [(d.name, d.hostapi) for d in filtered] == [
        ("Headset (Baseus Bowie WM02)", "Windows WASAPI"),
        (
            "Microphone Array (Intel® Smart Sound Technology for Digital Microphones)",
            "Windows WASAPI",
        ),
        ("Stereo Mix (Realtek HD Audio Stereo input)", "Windows WDM-KS"),
        ("Microphone (Realtek HD Audio Mic input)", "Windows WDM-KS"),
        ("Microphone Array 1 ()", "Windows WDM-KS"),
        ("Microphone Array 2 ()", "Windows WDM-KS"),
        ("Microphone (Realtek USB Audio)", "Windows WDM-KS"),
        ("Microphone (VIAVAD Wave)", "Windows WDM-KS"),
    ]


def test_devices_with_distinct_names_under_31_chars_are_not_merged():
    filtered = preferred_input_devices(_REAL_MACHINE_DEVICES)
    names = {d.name for d in filtered}
    assert "Microphone Array 1 ()" in names
    assert "Microphone Array 2 ()" in names


def test_preserves_first_occurrence_order_between_groups():
    filtered = preferred_input_devices(_REAL_MACHINE_DEVICES)
    names = [d.name for d in filtered]
    assert names.index("Headset (Baseus Bowie WM02)") < names.index(
        "Stereo Mix (Realtek HD Audio Stereo input)"
    )


def test_returns_empty_list_for_no_devices():
    assert preferred_input_devices([]) == []


# --- frame_samples_for_rate (F6) ----------------------------------------
#
# The capture stream used to force samplerate=16000 regardless of the
# device's native rate, so Windows resampled every buffer on the way in.
# Opening at the device's own default rate removes that step, but the frame
# size (in samples) has to move with it to keep each frame at the 20ms the
# detector's rolling windows assume one frame equals.


def test_matches_the_old_hardcoded_value_at_16khz():
    # 320 samples at 16 kHz / 20 ms -- the constant this replaces.
    assert frame_samples_for_rate(16_000, frame_ms=20) == 320


def test_divides_evenly_at_44100hz():
    assert frame_samples_for_rate(44_100, frame_ms=20) == 882


def test_divides_evenly_at_48000hz():
    assert frame_samples_for_rate(48_000, frame_ms=20) == 960


def test_rounds_to_the_nearest_sample_when_it_does_not_divide_evenly():
    # 11025 * 20 / 1000 = 220.5 -- not a whole number of samples.
    result = frame_samples_for_rate(11_025, frame_ms=20)
    assert result in (220, 221)  # nearest integer either way of the tie
    assert isinstance(result, int)


def test_never_returns_zero_even_for_a_tiny_rate():
    assert frame_samples_for_rate(10, frame_ms=20) >= 1


def test_defaults_frame_ms_to_the_configured_frame_duration():
    from stfu.config import FRAME_MS

    assert frame_samples_for_rate(16_000) == frame_samples_for_rate(
        16_000, frame_ms=FRAME_MS
    )
