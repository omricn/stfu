from stfu.detector import Cooldown


def test_first_event_is_always_allowed():
    gate = Cooldown(seconds=30)
    assert gate.allows(now=100.0) is True


def test_event_inside_the_window_is_blocked():
    gate = Cooldown(seconds=30)
    gate.mark(now=100.0)
    assert gate.allows(now=115.0) is False


def test_event_exactly_at_the_boundary_is_allowed():
    gate = Cooldown(seconds=30)
    gate.mark(now=100.0)
    assert gate.allows(now=130.0) is True


def test_event_after_the_window_is_allowed():
    gate = Cooldown(seconds=30)
    gate.mark(now=100.0)
    assert gate.allows(now=131.0) is True


def test_marking_again_restarts_the_window():
    gate = Cooldown(seconds=30)
    gate.mark(now=100.0)
    gate.mark(now=120.0)
    assert gate.allows(now=145.0) is False
    assert gate.allows(now=150.0) is True


def test_remaining_reports_seconds_left():
    gate = Cooldown(seconds=30)
    gate.mark(now=100.0)
    assert gate.remaining(now=110.0) == 20.0
    assert gate.remaining(now=200.0) == 0.0


def test_reset_clears_the_gate():
    gate = Cooldown(seconds=30)
    gate.mark(now=100.0)
    gate.reset()
    assert gate.allows(now=101.0) is True
