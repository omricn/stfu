"""Session state machine: which action does this trigger deserve?

The ladder has exactly two rungs and never climbs back down within a session.
"""

from __future__ import annotations

from datetime import datetime, timedelta

ACTION_OVERLAY = "overlay_4click"
ACTION_DESKTOP_DROP = "desktop_drop"


class StrikeManager:
    def __init__(
        self,
        reset_mode: str = "session",
        rolling_minutes: int = 60,
        nightly_hour: int = 4,
    ) -> None:
        self.reset_mode = reset_mode
        self.rolling_minutes = rolling_minutes
        self.nightly_hour = nightly_hour
        self.strike_count = 0
        self.session_id: str | None = None
        self._last_trigger: datetime | None = None

    def on_trigger(self, now: datetime) -> tuple[str, int]:
        """Record a trigger and return (action_name, strike_index)."""
        if self._should_reset(now):
            self._reset()

        if self.session_id is None:
            self.session_id = now.isoformat(timespec="seconds")

        self.strike_count += 1
        self._last_trigger = now

        action = ACTION_OVERLAY if self.strike_count == 1 else ACTION_DESKTOP_DROP
        return action, self.strike_count

    def end_session(self) -> None:
        """Called on app exit, logoff, or sleep."""
        self._reset()

    def _reset(self) -> None:
        self.strike_count = 0
        self.session_id = None
        self._last_trigger = None

    def _should_reset(self, now: datetime) -> bool:
        if self._last_trigger is None:
            return False
        if self.reset_mode == "rolling_60m":
            return now - self._last_trigger > timedelta(minutes=self.rolling_minutes)
        if self.reset_mode == "nightly":
            return self._night_of(now) != self._night_of(self._last_trigger)
        return False  # "session" resets only via end_session()

    def _night_of(self, moment: datetime) -> str:
        """The calendar date a moment belongs to, where a night runs until the
        cutover hour. 02:00 on the 18th belongs to the night of the 17th."""
        anchor = moment if moment.hour >= self.nightly_hour else moment - timedelta(days=1)
        return anchor.date().isoformat()
