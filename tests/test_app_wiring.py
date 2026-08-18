from stfu.app import DeviceWatch


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
