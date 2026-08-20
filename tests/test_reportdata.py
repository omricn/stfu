from datetime import datetime

from stfu.reportdata import (
    csv_rows,
    off_windows,
    session_summary,
    table_rows,
    trigger_points,
)


EVENTS = [
    {"ts": "2026-08-17T20:00:00", "type": "session_start", "session_id": "s1"},
    {
        "ts": "2026-08-17T20:05:00",
        "type": "trigger",
        "session_id": "s1",
        "trigger": "spike",
        "level_dbfs": -8.3,
        "threshold_dbfs": -12.0,
        "strike_index": 1,
        "action": "overlay_4click",
    },
    {"ts": "2026-08-17T20:30:00", "type": "mic_lost", "session_id": "s1"},
    {
        "ts": "2026-08-17T21:00:00",
        "type": "trigger",
        "session_id": "s1",
        "trigger": "spike",
        "level_dbfs": -6.0,
        "threshold_dbfs": -12.0,
        "strike_index": 2,
        "action": "desktop_drop",
    },
]


def test_trigger_points_returns_one_point_per_trigger():
    assert len(trigger_points(EVENTS)) == 2


def test_trigger_points_ignores_non_triggers():
    actions = [point.action for point in trigger_points(EVENTS)]
    assert "mic_lost" not in actions


def test_trigger_points_carry_time_level_and_action():
    first = trigger_points(EVENTS)[0]
    assert first.at.hour == 20
    assert first.level_dbfs == -8.3
    assert first.action == "overlay_4click"


def test_table_rows_include_non_trigger_events():
    kinds = [row.kind for row in table_rows(EVENTS)]
    assert "mic_lost" in kinds


def test_table_rows_are_in_time_order():
    times = [row.at for row in table_rows(EVENTS)]
    assert times == sorted(times)


def test_a_malformed_timestamp_is_dropped_from_the_table():
    # Exactly the valid rows, not "at least" them. A >= assertion would also
    # pass if the malformed row stopped being filtered at all.
    events = EVENTS + [{"ts": "not a time", "type": "trigger", "session_id": "s1"}]
    assert len(table_rows(events)) == len(EVENTS)


def test_a_trigger_missing_a_level_is_tolerated():
    events = [{"ts": "2026-08-17T20:00:00", "type": "trigger", "session_id": "s1"}]
    assert trigger_points(events)[0].level_dbfs is None


def test_the_summary_counts_triggers_and_names_the_worst():
    summary = session_summary(EVENTS)
    assert summary.trigger_count == 2
    assert summary.loudest_dbfs == -6.0


def test_the_summary_reports_the_span():
    summary = session_summary(EVENTS)
    assert summary.first_at.hour == 20
    assert summary.last_at.hour == 21


def test_an_empty_session_summarises_to_zero():
    summary = session_summary([])
    assert summary.trigger_count == 0
    assert summary.loudest_dbfs is None


def test_csv_rows_start_with_a_header():
    rows = csv_rows(EVENTS)
    assert rows[0] == ["time", "type", "trigger", "level_dbfs", "strike", "action"]


def test_csv_rows_cover_every_event():
    assert len(csv_rows(EVENTS)) == len(EVENTS) + 1


def test_the_summary_counts_a_trigger_with_an_unreadable_timestamp():
    # The chart cannot plot it, but the count must still include it.
    events = EVENTS + [{"ts": "not a time", "type": "trigger", "session_id": "s1"}]
    summary = session_summary(events)
    assert summary.trigger_count == 3
    assert summary.unreadable_count == 1


def test_a_clean_session_reports_nothing_unreadable():
    assert session_summary(EVENTS).unreadable_count == 0


def event(kind, ts):
    return {"type": kind, "ts": ts}


def test_off_windows_pairs_a_suspend_with_its_resume():
    spans = off_windows(
        [
            event("schedule_suspended", "2026-08-20T07:00:00"),
            event("trigger", "2026-08-20T08:00:00"),
            event("schedule_resumed", "2026-08-20T22:00:00"),
        ]
    )
    assert spans == [(datetime(2026, 8, 20, 7, 0), datetime(2026, 8, 20, 22, 0))]


def test_off_windows_leaves_an_unclosed_span_open():
    # The app exited inside the window, so no resume was ever written.
    spans = off_windows([event("schedule_suspended", "2026-08-20T07:00:00")])
    assert spans == [(datetime(2026, 8, 20, 7, 0), None)]


def test_off_windows_ignores_a_resume_with_no_suspend():
    # The log is append-only and may start mid-window.
    assert off_windows([event("schedule_resumed", "2026-08-20T22:00:00")]) == []


def test_off_windows_handles_several_spans_and_unsorted_input():
    spans = off_windows(
        [
            event("schedule_resumed", "2026-08-20T22:00:00"),
            event("schedule_suspended", "2026-08-20T07:00:00"),
            event("schedule_suspended", "2026-08-21T07:00:00"),
            event("schedule_resumed", "2026-08-21T22:00:00"),
        ]
    )
    assert len(spans) == 2
    assert spans[0][0] == datetime(2026, 8, 20, 7, 0)
    assert spans[1][1] == datetime(2026, 8, 21, 22, 0)


def test_off_windows_skips_torn_lines():
    spans = off_windows(
        [
            {"type": "schedule_suspended", "ts": "not-a-timestamp"},
            event("schedule_suspended", "2026-08-20T07:00:00"),
            event("schedule_resumed", "2026-08-20T22:00:00"),
        ]
    )
    assert spans == [(datetime(2026, 8, 20, 7, 0), datetime(2026, 8, 20, 22, 0))]


def test_off_windows_ignores_a_duplicate_suspend():
    # Two suspends with no resume between them: keep the first, so the span
    # covers everything that was actually switched off.
    spans = off_windows(
        [
            event("schedule_suspended", "2026-08-20T07:00:00"),
            event("schedule_suspended", "2026-08-20T09:00:00"),
            event("schedule_resumed", "2026-08-20T22:00:00"),
        ]
    )
    assert spans == [(datetime(2026, 8, 20, 7, 0), datetime(2026, 8, 20, 22, 0))]


def test_schedule_events_reach_the_detail_table():
    # table_rows is generic over event type; this locks that in so the two
    # new kinds cannot be dropped by a later refactor.
    rows = table_rows(
        [
            event("schedule_suspended", "2026-08-20T07:00:00"),
            event("schedule_resumed", "2026-08-20T22:00:00"),
        ]
    )
    assert [r.kind for r in rows] == ["schedule_suspended", "schedule_resumed"]


def test_csv_export_keeps_iso_timestamps_for_schedule_events():
    rows = csv_rows([event("schedule_suspended", "2026-08-20T07:00:00")])
    assert rows[1][0] == "2026-08-20T07:00:00"
    assert rows[1][1] == "schedule_suspended"


def test_off_windows_finds_records_that_session_filtering_would_miss(tmp_path):
    """The reason reportui must pass the whole log, not one session's events.

    The engine stamps boundary records with whatever session was open, and
    during quiet hours there is none -- so they carry session_id None, and
    LogStore.events_for_session matches by equality and never returns them.
    Reading the filtered list would find no spans at all, silently.
    """
    from stfu.logstore import LogStore

    store = LogStore(tmp_path / "events.jsonl")
    store.append(type="session_start", session_id="s1", ts="2026-08-19T23:00:00")
    store.append(type="schedule_suspended", session_id=None, ts="2026-08-20T07:00:00")
    store.append(type="schedule_resumed", session_id=None, ts="2026-08-20T22:00:00")

    assert off_windows(store.events_for_session("s1")) == []
    assert len(off_windows(store.read_all())) == 1


def test_a_log_mixing_naive_and_aware_timestamps_is_still_readable():
    """The report window crashed outright on any log holding both kinds.

    Engine-written records carry a naive `wall.isoformat()`. Records that let
    LogStore.append stamp its own -- mic_lost, mic_found, app_paused,
    app_resumed -- carry an aware one. Sorting them together raised TypeError,
    so Report was unopenable for anyone whose microphone had ever dropped
    mid-session or who had ever used Pause 15 min.

    Asserts on count and tz-naivety rather than on order, because converting
    the aware record to local time makes its position machine-dependent.
    """
    mixed = [
        event("trigger", "2026-08-19T23:01:00"),
        event("mic_lost", "2026-08-19T23:02:00+03:00"),
        event("mic_found", "2026-08-19T23:03:00+03:00"),
    ]

    rows = table_rows(mixed)
    assert len(rows) == 3
    assert all(row.at.tzinfo is None for row in rows)


def test_session_summary_survives_a_mixed_log():
    """reportui's off-hours band clipping depends on this not raising."""
    info = session_summary(
        [
            event("trigger", "2026-08-19T23:01:00"),
            event("mic_lost", "2026-08-19T23:02:00+03:00"),
        ]
    )
    assert info.first_at is not None
    assert info.last_at is not None
    assert info.first_at.tzinfo is None


def test_an_aware_timestamp_renders_as_local_wall_clock():
    """An aware record must not be displayed shifted by the local offset."""
    from datetime import datetime as dt, timedelta, timezone

    # Build an offset that is definitely not this machine's, then check the
    # parsed value equals the same instant expressed in local time.
    aware = dt(2026, 8, 19, 23, 0, tzinfo=timezone(timedelta(hours=-7)))
    rows = table_rows([event("mic_lost", aware.isoformat())])
    assert rows[0].at == aware.astimezone().replace(tzinfo=None)
