from stfu.reportdata import csv_rows, session_summary, table_rows, trigger_points


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
