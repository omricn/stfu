"""Append-only JSONL event log.

One JSON object per line. A partial write costs at most the final line, and
readers skip anything that will not parse, so history is never lost to a crash.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPES = (
    "trigger",
    "session_start",
    "session_end",
    "mic_lost",
    "mic_found",
    "app_paused",
    "app_resumed",
)


class LogStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, *, type: str, **fields) -> dict:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {type!r}")
        event = {"ts": datetime.now().astimezone().isoformat(), "type": type}
        # update() lets a caller-supplied "ts" overwrite the generated one, so
        # replayed or backdated events keep their original timestamp.
        event.update(fields)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
        return event

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        events = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # torn write; skip it
        return events

    def events_for_session(self, session_id: str) -> list[dict]:
        return [e for e in self.read_all() if e.get("session_id") == session_id]

    def sessions(self) -> list[str]:
        """Distinct session ids, newest first by their earliest timestamp."""
        first_seen: dict[str, str] = {}
        for event in self.read_all():
            session_id = event.get("session_id")
            if session_id and session_id not in first_seen:
                first_seen[session_id] = event.get("ts", "")
        return sorted(first_seen, key=lambda s: _instant(first_seen[s]), reverse=True)


def _instant(ts: str) -> datetime:
    """Parse a timestamp for ordering, tolerating missing or malformed values.

    Comparing the ISO strings directly is only correct while every timestamp
    carries the same UTC offset. `append` stamps the local offset, so on a DST
    transition day a "-04:00" timestamp can sort before a "+00:00" one that is
    genuinely earlier. Anything unparseable sorts oldest.
    """
    try:
        parsed = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
