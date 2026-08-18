from stfu.audio import FakeSource
from stfu.calibration import collect_sample
from stfu.levels import rms_from_dbfs


def source_at(level_dbfs, frames):
    return FakeSource([rms_from_dbfs(level_dbfs)] * frames)


def test_it_collects_the_requested_number_of_frames():
    levels = collect_sample(source_at(-40.0, 500), frames=100)
    assert len(levels) == 100


def test_it_converts_to_dbfs():
    levels = collect_sample(source_at(-40.0, 200), frames=10)
    assert all(abs(level + 40.0) < 0.01 for level in levels)


def test_it_stops_early_when_the_source_runs_out():
    levels = collect_sample(source_at(-40.0, 7), frames=100)
    assert len(levels) == 7


def test_progress_is_reported():
    seen = []
    collect_sample(source_at(-40.0, 100), frames=10, on_progress=seen.append)
    assert len(seen) == 10
    assert seen[-1] == 1.0
    assert seen[0] < seen[-1]


def test_a_cancel_flag_stops_collection():
    stop_after = {"count": 0}

    def cancelled():
        stop_after["count"] += 1
        return stop_after["count"] > 5

    levels = collect_sample(source_at(-40.0, 100), frames=50, is_cancelled=cancelled)
    assert len(levels) < 50


def test_zero_frames_returns_nothing():
    assert collect_sample(source_at(-40.0, 10), frames=0) == []
