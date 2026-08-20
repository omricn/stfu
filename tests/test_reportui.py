from stfu.config import Config
from stfu.logstore import LogStore
from stfu.reportui import ReportWindow


def window(tmp_path, config=None):
    """ReportWindow.__init__ touches no Tk -- only show() does -- so the
    clock-format plumbing can be tested without a display."""
    return ReportWindow(None, LogStore(tmp_path / "events.jsonl"), config)


def test_the_clock_format_comes_from_the_config(tmp_path):
    assert window(tmp_path, Config(clock_format="12h"))._clock() == "12h"
    assert window(tmp_path, Config(clock_format="24h"))._clock() == "24h"


def test_no_config_falls_back_to_twenty_four_hour(tmp_path):
    # The window can still be constructed without a config, as tests do.
    # 24-hour is what it rendered before the setting existed.
    assert window(tmp_path)._clock() == "24h"
    assert window(tmp_path, None)._clock() == "24h"
