import pytest

from stfu.instance import FakeLock, SingleInstance


def test_the_first_acquire_succeeds():
    assert SingleInstance(FakeLock()).acquire() is True


def test_a_second_acquire_on_the_same_lock_fails():
    lock = FakeLock()
    assert SingleInstance(lock).acquire() is True
    assert SingleInstance(lock).acquire() is False


def test_releasing_lets_another_instance_in():
    lock = FakeLock()
    first = SingleInstance(lock)
    first.acquire()
    first.release()
    assert SingleInstance(lock).acquire() is True


def test_release_without_acquire_is_not_an_error():
    SingleInstance(FakeLock()).release()


def test_double_release_is_not_an_error():
    lock = FakeLock()
    guard = SingleInstance(lock)
    guard.acquire()
    guard.release()
    guard.release()


def test_it_works_as_a_context_manager():
    lock = FakeLock()
    with SingleInstance(lock) as acquired:
        assert acquired is True
        assert SingleInstance(lock).acquire() is False
    assert SingleInstance(lock).acquire() is True


def test_the_context_manager_releases_even_on_an_exception():
    lock = FakeLock()
    with pytest.raises(RuntimeError):
        with SingleInstance(lock):
            raise RuntimeError("boom")
    assert SingleInstance(lock).acquire() is True


def test_the_mutex_is_session_scoped_not_global():
    # Global\ needs SeCreateGlobalPrivilege, which a standard user may lack
    # under RDP or a locked-down session -- CreateMutexW would then fail
    # outright rather than reporting the instance already exists.
    from stfu.instance import MUTEX_NAME

    assert MUTEX_NAME.startswith("Local\\")
