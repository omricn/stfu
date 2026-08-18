from stfu.autostart import RUN_KEY, VALUE_NAME, FakeRegistry, disable, enable, is_enabled


def test_starts_disabled():
    assert is_enabled(FakeRegistry()) is False


def test_enable_writes_the_command():
    registry = FakeRegistry()
    enable(r"C:\Apps\stfu.exe", registry)
    assert registry.values[(RUN_KEY, VALUE_NAME)] == r'"C:\Apps\stfu.exe"'


def test_enable_is_idempotent():
    registry = FakeRegistry()
    enable(r"C:\Apps\stfu.exe", registry)
    enable(r"C:\Apps\stfu.exe", registry)
    assert len(registry.values) == 1


def test_enable_then_query_reports_enabled():
    registry = FakeRegistry()
    enable(r"C:\Apps\stfu.exe", registry)
    assert is_enabled(registry) is True


def test_disable_removes_the_entry():
    registry = FakeRegistry()
    enable(r"C:\Apps\stfu.exe", registry)
    disable(registry)
    assert is_enabled(registry) is False


def test_disable_when_absent_is_not_an_error():
    disable(FakeRegistry())  # must not raise


def test_a_path_with_spaces_is_quoted():
    registry = FakeRegistry()
    enable(r"C:\Program Files\S.TFU\stfu.exe", registry)
    stored = registry.values[(RUN_KEY, VALUE_NAME)]
    assert stored.startswith('"') and stored.endswith('"')


def test_enable_replaces_an_older_path():
    registry = FakeRegistry()
    enable(r"C:\Old\stfu.exe", registry)
    enable(r"C:\New\stfu.exe", registry)
    assert registry.values[(RUN_KEY, VALUE_NAME)] == r'"C:\New\stfu.exe"'
