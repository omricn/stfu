"""Shaping log events into what the report window draws.

Pure, so the report's arithmetic is testable without matplotlib or a window.
Every function tolerates malformed records: the log is append-only and may
contain a torn line or an event written by an older version.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

CSV_HEADER = ["time", "type", "trigger", "level_dbfs", "strike", "action"]


@dataclass(frozen=True)
class TriggerPoint:
    at: datetime
    level_dbfs: float | None
    threshold_dbfs: float | None
    action: str
    kind: str


@dataclass(frozen=True)
class TableRow:
    at: datetime
    kind: str
    trigger: str
    level_dbfs: float | None
    strike_index: int | None
    action: str


@dataclass(frozen=True)
class SessionSummary:
    trigger_count: int
    loudest_dbfs: float | None
    first_at: datetime | None
    last_at: datetime | None
    unreadable_count: int


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(ts) if ts else None
    except (TypeError, ValueError):
        return None


def trigger_points(events: list[dict]) -> list[TriggerPoint]:
    points = []
    for event in events:
        if event.get("type") != "trigger":
            continue
        at = _parse(event.get("ts"))
        if at is None:
            continue
        points.append(
            TriggerPoint(
                at=at,
                level_dbfs=event.get("level_dbfs"),
                threshold_dbfs=event.get("threshold_dbfs"),
                action=event.get("action", ""),
                kind=event.get("trigger", ""),
            )
        )
    return sorted(points, key=lambda p: p.at)


def table_rows(events: list[dict]) -> list[TableRow]:
    """Every event, including mic loss and pauses -- gaps in coverage matter."""
    rows = []
    for event in events:
        at = _parse(event.get("ts"))
        if at is None:
            continue
        rows.append(
            TableRow(
                at=at,
                kind=event.get("type", ""),
                trigger=event.get("trigger", ""),
                level_dbfs=event.get("level_dbfs"),
                strike_index=event.get("strike_index"),
                action=event.get("action", ""),
            )
        )
    return sorted(rows, key=lambda r: r.at)


def session_summary(events: list[dict]) -> SessionSummary:
    points = trigger_points(events)
    levels = [p.level_dbfs for p in points if p.level_dbfs is not None]
    rows = table_rows(events)

    # Counted from the raw events, not from the plottable ones. A torn log line
    # cannot be charted, but "how many times did he yell" must not quietly
    # undercount because of it.
    triggers = [e for e in events if e.get("type") == "trigger"]
    unreadable = [e for e in events if _parse(e.get("ts")) is None]

    return SessionSummary(
        trigger_count=len(triggers),
        loudest_dbfs=max(levels) if levels else None,
        first_at=rows[0].at if rows else None,
        last_at=rows[-1].at if rows else None,
        unreadable_count=len(unreadable),
    )


def csv_rows(events: list[dict]) -> list[list]:
    rows = [CSV_HEADER]
    for event in events:
        rows.append(
            [
                event.get("ts", ""),
                event.get("type", ""),
                event.get("trigger", ""),
                event.get("level_dbfs", ""),
                event.get("strike_index", ""),
                event.get("action", ""),
            ]
        )
    return rows
