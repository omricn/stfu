from datetime import datetime

import pytest

from stfu.logstore import EVENT_TYPES, LogStore


@pytest.fixture
def store(tmp_path):
    return LogStore(tmp_path / "events.jsonl")


def test_append_then_read_round_trips(store):
    store.append(type="trigger", session_id="s1", peak_dbfs=-8.3)
    events = store.read_all()
    assert len(events) == 1
    assert events[0]["type"] == "trigger"
    assert events[0]["peak_dbfs"] == -8.3


def test_every_event_gets_a_timestamp(store):
    store.append(type="session_start", session_id="s1")
    assert "ts" in store.read_all()[0]
    datetime.fromisoformat(store.read_all()[0]["ts"])  # parses without raising


def test_a_supplied_timestamp_is_kept(store):
    store.append(type="trigger", session_id="s1", ts="2026-08-17T21:43:12")
    assert store.read_all()[0]["ts"] == "2026-08-17T21:43:12"


def test_clear_deletes_the_log_file(store):
    store.append(type="trigger", session_id="s1")
    assert store.path.exists()

    store.clear()

    assert not store.path.exists()
    assert store.read_all() == []


def test_clear_with_no_log_yet_is_not_an_error(store):
    store.clear()  # must not raise
    assert store.read_all() == []


def test_reading_a_missing_file_gives_an_empty_list(tmp_path):
    assert LogStore(tmp_path / "nothing.jsonl").read_all() == []


def test_appending_creates_the_parent_directory(tmp_path):
    store = LogStore(tmp_path / "nested" / "deep" / "events.jsonl")
    store.append(type="trigger", session_id="s1")
    assert len(store.read_all()) == 1


def test_a_corrupt_line_is_skipped_not_fatal(store):
    store.append(type="trigger", session_id="s1")
    with store.path.open("a", encoding="utf-8") as handle:
        handle.write("{ half a line\n")
    store.append(type="trigger", session_id="s1")
    assert len(store.read_all()) == 2


def test_events_can_be_filtered_by_session(store):
    store.append(type="trigger", session_id="s1")
    store.append(type="trigger", session_id="s2")
    store.append(type="trigger", session_id="s1")
    assert len(store.events_for_session("s1")) == 2


def test_sessions_are_listed_newest_first(store):
    store.append(type="session_start", session_id="s1", ts="2026-08-16T19:00:00")
    store.append(type="session_start", session_id="s2", ts="2026-08-17T19:00:00")
    assert store.sessions() == ["s2", "s1"]


def test_rejects_an_unknown_event_type(store):
    with pytest.raises(ValueError):
        store.append(type="banana", session_id="s1")


def test_all_spec_event_types_are_accepted(store):
    for event_type in EVENT_TYPES:
        store.append(type=event_type, session_id="s1")
    assert len(store.read_all()) == len(EVENT_TYPES)


def test_sessions_sort_by_real_time_not_string_order(store):
    # Same calendar date, different UTC offsets: 19:00-04:00 is 23:00 UTC and
    # genuinely later than 20:00+00:00, but sorts earlier as a plain string.
    # Reachable on a DST transition day, since append() stamps the local offset.
    store.append(
        type="session_start", session_id="early", ts="2026-08-17T20:00:00+00:00"
    )
    store.append(
        type="session_start", session_id="late", ts="2026-08-17T19:00:00-04:00"
    )
    assert store.sessions() == ["late", "early"]


def test_sessions_tolerate_an_unparseable_timestamp(store):
    store.append(type="session_start", session_id="good", ts="2026-08-17T19:00:00")
    store.append(type="session_start", session_id="bad", ts="not a timestamp")
    assert store.sessions() == ["good", "bad"]
