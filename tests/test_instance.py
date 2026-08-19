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


def _fake_clock(start: float = 0.0):
    """A (now, sleep) pair that advances a shared clock by however long
    `sleep` is asked to wait, so retry tests never actually block."""
    state = {"t": start}

    def now() -> float:
        return state["t"]

    def sleep(seconds: float) -> None:
        state["t"] += seconds

    return now, sleep


def test_acquire_with_no_retry_fails_immediately_when_held():
    lock = FakeLock()
    SingleInstance(lock).acquire()
    assert SingleInstance(lock).acquire(retry_seconds=0.0) is False


def test_acquire_retries_until_the_lock_frees_up():
    lock = FakeLock()
    holder = SingleInstance(lock)
    holder.acquire()

    now, sleep = _fake_clock()
    releases_after = {"count": 0}

    def sleep_and_release(seconds: float) -> None:
        sleep(seconds)
        releases_after["count"] += 1
        if releases_after["count"] == 2:
            holder.release()

    waiter = SingleInstance(lock)
    acquired = waiter.acquire(
        retry_seconds=5.0, poll_interval=1.0, sleep=sleep_and_release, now=now
    )

    assert acquired is True
    assert releases_after["count"] == 2


def test_acquire_gives_up_once_retry_seconds_elapse():
    lock = FakeLock()
    SingleInstance(lock).acquire()  # held for the whole test; never released

    now, sleep = _fake_clock()
    waiter = SingleInstance(lock)

    assert (
        waiter.acquire(retry_seconds=3.0, poll_interval=1.0, sleep=sleep, now=now)
        is False
    )


def test_the_mutex_is_session_scoped_not_global():
    # Global\ needs SeCreateGlobalPrivilege, which a standard user may lack
    # under RDP or a locked-down session -- CreateMutexW would then fail
    # outright rather than reporting the instance already exists.
    from stfu.instance import MUTEX_NAME

    assert MUTEX_NAME.startswith("Local\\")
