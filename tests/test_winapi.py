from stfu.winapi import FakeWinApi


def test_fake_records_a_minimise():
    api = FakeWinApi()
    assert api.minimize_foreground() is True
    assert api.calls == ["minimize_foreground"]


def test_fake_records_a_desktop_show():
    api = FakeWinApi()
    api.show_desktop()
    assert api.calls == ["show_desktop"]


def test_fake_records_calls_in_order():
    api = FakeWinApi()
    api.minimize_foreground()
    api.show_desktop()
    api.minimize_foreground()
    assert api.calls == ["minimize_foreground", "show_desktop", "minimize_foreground"]


def test_fake_can_simulate_a_failed_minimise():
    api = FakeWinApi(minimize_succeeds=False)
    assert api.minimize_foreground() is False
    assert api.calls == ["minimize_foreground"]
