from stfu.app import App, DeviceWatch, perform_start_over
from stfu.tray import STATE_LISTENING, STATE_NO_MIC, STATE_SCHEDULED_OFF


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def advance(self, seconds):
        self.now += seconds


def test_it_starts_assuming_the_device_is_present():
    watch = DeviceWatch(poll_seconds=5.0)
    assert watch.present is True


def test_losing_the_device_is_reported_once():
    watch = DeviceWatch(poll_seconds=5.0)
    assert watch.update(present=False, now=0.0) == "lost"
    assert watch.update(present=False, now=1.0) is None


def test_regaining_the_device_is_reported_once():
    watch = DeviceWatch(poll_seconds=5.0)
    watch.update(present=False, now=0.0)
    assert watch.update(present=True, now=6.0) == "found"
    assert watch.update(present=True, now=7.0) is None


def test_it_only_polls_after_the_interval():
    watch = DeviceWatch(poll_seconds=5.0)
    watch.update(present=False, now=0.0)
    assert watch.should_poll(now=2.0) is False
    assert watch.should_poll(now=5.0) is True


def test_flapping_produces_one_event_per_transition():
    watch = DeviceWatch(poll_seconds=0.0)
    events = [
        watch.update(present=False, now=0.0),
        watch.update(present=True, now=1.0),
        watch.update(present=False, now=2.0),
    ]
    assert events == ["lost", "found", "lost"]


class Recorder:
    """Records which of spawn/reset/request_exit ran, and in what order --
    perform_start_over()'s ordering is exactly the thing under test."""

    def __init__(self, spawn_raises: bool = False) -> None:
        self.calls: list[str] = []
        self._spawn_raises = spawn_raises

    def spawn(self) -> None:
        self.calls.append("spawn")
        if self._spawn_raises:
            raise OSError("could not start the new process")

    def reset(self) -> None:
        self.calls.append("reset")

    def request_exit(self) -> None:
        self.calls.append("request_exit")


def test_a_successful_relaunch_resets_then_exits():
    rec = Recorder()
    result = perform_start_over(rec.spawn, rec.reset, rec.request_exit)
    assert result is True
    assert rec.calls == ["spawn", "reset", "request_exit"]


def test_a_failed_relaunch_touches_nothing_else():
    # This is the one way "Start over" could brick the app: state wiped with
    # no process left running. A relaunch failure must be a no-op instead.
    rec = Recorder(spawn_raises=True)
    result = perform_start_over(rec.spawn, rec.reset, rec.request_exit)
    assert result is False
    assert rec.calls == ["spawn"]


class _FakeEngine:
    """Stands in for the real Engine -- _listening_state only ever reads
    .scheduled_off off of it."""

    def __init__(self, scheduled_off: bool) -> None:
        self.scheduled_off = scheduled_off


class _AppLike:
    """A duck-typed stand-in for the `self` that App._listening_state()
    expects. Constructing a real App drags in a live MicSource, Engine,
    and Tray (pystray, sounddevice) -- not practical for a unit test, and
    the method itself only touches self.engine, so this is enough to
    exercise the real method body unmodified."""

    def __init__(self, scheduled_off: bool) -> None:
        self.engine = _FakeEngine(scheduled_off)


def test_listening_state_prefers_no_mic_over_scheduled_off():
    # Mic absent and scheduled off -- a fault must not be hidden behind a
    # state that says everything is fine on purpose.
    app_like = _AppLike(scheduled_off=True)
    assert App._listening_state(app_like, mic_present=False) == STATE_NO_MIC


def test_listening_state_reports_scheduled_off_when_mic_present():
    app_like = _AppLike(scheduled_off=True)
    assert App._listening_state(app_like, mic_present=True) == STATE_SCHEDULED_OFF


def test_listening_state_reports_listening_when_neither_applies():
    app_like = _AppLike(scheduled_off=False)
    assert App._listening_state(app_like, mic_present=True) == STATE_LISTENING
