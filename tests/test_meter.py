import threading

from stfu.levels import MIN_DBFS
from stfu.meter import MeterState


def test_initial_reading_is_silent_and_assumes_the_mic_present():
    reading = MeterState().read()
    assert reading.dbfs == MIN_DBFS
    assert reading.cooldown_remaining_s == 0.0
    assert reading.mic_present is True


def test_update_is_reflected_in_the_next_read():
    state = MeterState()
    state.update(dbfs=-12.5, threshold_dbfs=-10.0, cooldown_remaining_s=7.5, mic_present=True)
    reading = state.read()
    assert reading.dbfs == -12.5
    assert reading.threshold_dbfs == -10.0
    assert reading.cooldown_remaining_s == 7.5
    assert reading.mic_present is True


def test_a_reading_is_never_a_mix_of_two_updates():
    """Every field in one read() must come from the same update() call.

    Hammers update() from one thread while read() runs on the main thread and
    checks every observed reading is internally consistent -- dbfs and
    cooldown always agree on which update produced them -- rather than
    happening to not catch a torn read in a fixed number of iterations.
    """
    state = MeterState()
    stop = threading.Event()
    mismatches = []

    def writer() -> None:
        i = 0
        while not stop.is_set():
            i += 1
            # dbfs and cooldown are deliberately tied together so a torn read
            # (one field from this update, one from the next) is detectable.
            state.update(
                dbfs=float(i), threshold_dbfs=-12.0, cooldown_remaining_s=float(i),
                mic_present=True,
            )

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        for _ in range(5000):
            reading = state.read()
            if reading.dbfs != reading.cooldown_remaining_s:
                mismatches.append(reading)
    finally:
        stop.set()
        thread.join(timeout=2.0)

    assert mismatches == []
