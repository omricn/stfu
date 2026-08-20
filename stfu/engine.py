"""Wires source, detector, strikes, actions, and log together.

Two clocks are threaded through deliberately. `mono` is a monotonic seconds
value used for every duration decision (cooldown, suppression), because wall
time can jump backwards across DST and NTP corrections and a jump backwards
would freeze the cooldown. `wall` is real calendar time, used for session
boundaries and log timestamps, which have to mean something to a human reading
the report.
"""

from __future__ import annotations

import logging
from datetime import datetime

from stfu import schedule
from stfu.audio import AudioSource
from stfu.clock import parse_time
from stfu.config import Config
from stfu.detector import Detector
from stfu.logstore import LogStore
from stfu.strikes import StrikeManager

log = logging.getLogger(__name__)

# Extra suppression after a clip finishes, so the tail of a clip cannot trigger.
SUPPRESSION_TAIL_S = 0.2


class Engine:
    def __init__(
        self,
        config: Config,
        source: AudioSource,
        actions,
        logstore: LogStore,
    ) -> None:
        self.config = config
        self.source = source
        self.actions = actions
        self.logstore = logstore
        self.detector = Detector(config)
        self.strikes = StrikeManager(
            reset_mode=config.session_reset_mode,
            rolling_minutes=config.rolling_reset_minutes,
            nightly_hour=config.nightly_reset_hour,
            overlay_strikes=config.overlay_strikes,
        )
        self.paused = False
        self._logged_session: str | None = None
        self._scheduled_off = False

    def handle_frame(self, rms: float, mono: float, wall: datetime) -> None:
        """Process one audio frame. The single entry point for detection."""
        if self.paused:
            return

        if self._update_schedule(wall):
            return

        event = self.detector.push(rms, now=mono)
        if event is None:
            return

        action, strike_index = self.strikes.on_trigger(wall)

        # Compare session ids rather than holding a bool. StrikeManager mints a
        # new id on a rolling or nightly rollover, and a flag set once at the
        # first trigger would suppress the new session's session_start, leaving
        # its triggers orphaned in the report with no beginning.
        if self._logged_session != self.strikes.session_id:
            if self._logged_session is not None:
                self.logstore.append(
                    type="session_end",
                    session_id=self._logged_session,
                    ts=wall.isoformat(),
                )
            self.logstore.append(
                type="session_start",
                session_id=self.strikes.session_id,
                ts=wall.isoformat(),
            )
            self._logged_session = self.strikes.session_id

        # Log before dispatching, stamped with the time of the yell rather than
        # the time of the write. An action may block indefinitely -- the overlay
        # waits for four clicks -- which would otherwise date every record to
        # when the action finished, and lose the record entirely if the process
        # is killed while the overlay is open. A dispatched-but-failed action
        # still writes its traceback to the app log.
        self.logstore.append(
            type="trigger",
            session_id=self.strikes.session_id,
            ts=wall.isoformat(),
            trigger=event.kind,
            level_dbfs=round(event.level_dbfs, 2),
            threshold_dbfs=round(event.threshold_dbfs, 2),
            strike_index=strike_index,
            action=action,
        )

        clip_seconds = self._fire(action, event)
        if clip_seconds is not None:
            self.detector.suppress_until(mono + clip_seconds + SUPPRESSION_TAIL_S)

    @property
    def scheduled_off(self) -> bool:
        """True while the configured off-hours window is in force.

        Named apart from the `schedule_suspended` / `schedule_resumed` event
        types so a reader never mistakes the live flag for a log record.
        """
        return self._scheduled_off

    def _update_schedule(self, wall: datetime) -> bool:
        """Track the off-hours window, returning True while it is in force.

        Evaluated from wall time on every frame rather than driven by a timer.
        A timer looks cheaper and is wrong here: this machine sleeps, and a
        boundary that falls during suspend never fires, leaving the app stuck
        in the wrong state indefinitely. A fixed delay would also drift an
        hour across a DST change. Recomputing costs two integer comparisons
        and is correct on wake, across DST, and after an NTP correction.

        Config is read every frame, so a change made in Settings takes effect
        immediately -- the same courtesy the sound folders already get.
        """
        off = False
        if self.config.schedule_enabled:
            start = parse_time(self.config.schedule_off_from)
            end = parse_time(self.config.schedule_off_to)
            # Unparseable times mean no window. _coerce should already have
            # disabled the schedule, so this is the second line of defence.
            if start is not None and end is not None:
                off = schedule.is_off(wall, start, end)

        if off != self._scheduled_off:
            self._scheduled_off = off
            if off:
                self.logstore.append(
                    type="schedule_suspended",
                    session_id=self.strikes.session_id,
                    ts=wall.isoformat(),
                )
            else:
                # Same reasoning as resume(): the rolling windows still hold
                # frames from before the window, potentially hours old, and
                # adaptive mode would compare live audio to that stale
                # baseline. Safe here only because nothing was being fed in.
                self.detector.reset()
                self.logstore.append(
                    type="schedule_resumed",
                    session_id=self.strikes.session_id,
                    ts=wall.isoformat(),
                )
        return off

    def _fire(self, action: str, event) -> float | None:
        """Dispatch an action. A failing action must never stop monitoring —
        a broken overlay is a much smaller problem than a dead detector."""
        try:
            return self.actions.fire(action, event)
        except Exception:
            log.exception("action %s failed", action)
            return None

    def pause(self) -> None:
        if self.paused:
            return
        self.paused = True
        self.logstore.append(type="app_paused", session_id=self.strikes.session_id)

    def resume(self) -> None:
        if not self.paused:
            return
        self.paused = False
        # Only safe because we were genuinely paused: reset() clears the rolling
        # windows, and doing that during live monitoring would blind detection
        # until they refill.
        self.detector.reset()
        self.logstore.append(type="app_resumed", session_id=self.strikes.session_id)

    def on_mic_lost(self) -> None:
        self.detector.reset()
        self.logstore.append(type="mic_lost", session_id=self.strikes.session_id)

    def on_mic_found(self) -> None:
        self.logstore.append(type="mic_found", session_id=self.strikes.session_id)

    def stop(self) -> None:
        if self._logged_session is not None:
            self.logstore.append(
                type="session_end", session_id=self._logged_session
            )
        self.strikes.end_session()
        self._logged_session = None
