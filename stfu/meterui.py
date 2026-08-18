"""The live meter window (F5).

"Is it even listening?" is a fair question the app previously gave no way
to answer -- a working 30s cooldown and a dead microphone look identical
from the outside. This window shows the current level, the threshold in
force, and (the actual point of it) the seconds left on the cooldown, so a
suppressed yell is visibly suppressed rather than apparently ignored.

Read-only diagnostics, opened from the tray with no PIN.

Feeding it: the capture thread already owns the one audio stream this app is
allowed to have open (see app.py's module docstring on nested Tk mainloops
and the three prior bugs from cross-thread Tk access) -- this window must not
open a second stream, and must not be pushed to from that thread directly.

Instead it reads a MeterState snapshot on its own timer. The frame rate is
50/s; shoving every one of those through UiBridge's submit/queue machinery
would be needless traffic on both threads for a number nobody can see change
that fast. Because this window's own show() already runs on the Tk thread
(opened once through the bridge, like every other window here), its
after()-driven refresh loop is just one more periodic callback alongside the
hidden root's own pump -- the same pattern the rest of this app already uses
for anything periodic, not a new cross-thread path.
"""

from __future__ import annotations

import tkinter as tk

from stfu.levels import meter_from_dbfs
from stfu.meter import MeterState

REFRESH_MS = 150
BAR_WIDTH = 320
BAR_HEIGHT = 28
BAR_BG = "#1c1c1c"
BAR_FILL = "#2ecc71"
BAR_OVER_THRESHOLD_FILL = "#e74c3c"
THRESHOLD_MARKER = "#f5f5f5"
COOLDOWN_ACTIVE_FG = "#f0a500"
COOLDOWN_READY_FG = "#2ecc71"


def _meter_x(dbfs: float) -> int:
    """Horizontal pixel position on the bar for a dBFS value, 0-100 scale."""
    return round(meter_from_dbfs(dbfs) / 100 * BAR_WIDTH)


class MeterWindow:
    """`show()` opens its own window and blocks the caller until it is
    closed, the same convention every other window in this project follows."""

    def __init__(self, meter: MeterState) -> None:
        self._meter = meter
        self.root: tk.Tk | None = None
        self._after_id: str | None = None

    def show(self) -> None:
        self.root = tk.Tk()
        self.root.title("S.TFU - live meter")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        self._level_label = tk.Label(
            self.root, text="", font=("Segoe UI", 16, "bold"), anchor="w"
        )
        self._level_label.pack(fill="x", padx=16, pady=(16, 4))

        self._canvas = tk.Canvas(
            self.root,
            width=BAR_WIDTH,
            height=BAR_HEIGHT,
            bg=BAR_BG,
            highlightthickness=0,
        )
        self._canvas.pack(padx=16, pady=4)
        self._bar = self._canvas.create_rectangle(
            0, 0, 0, BAR_HEIGHT, fill=BAR_FILL, width=0
        )
        self._threshold_marker = self._canvas.create_line(
            0, 0, 0, BAR_HEIGHT, fill=THRESHOLD_MARKER, width=2
        )

        self._threshold_label = tk.Label(self.root, text="", anchor="w")
        self._threshold_label.pack(fill="x", padx=16, pady=(4, 8))

        self._cooldown_label = tk.Label(
            self.root, text="", font=("Segoe UI", 13, "bold"), anchor="w"
        )
        self._cooldown_label.pack(fill="x", padx=16, pady=(0, 16))

        self._refresh()
        self.root.mainloop()

    def _refresh(self) -> None:
        reading = self._meter.read()

        if not reading.mic_present:
            self._level_label.configure(text="No microphone")
            self._canvas.coords(self._bar, 0, 0, 0, BAR_HEIGHT)
            self._threshold_label.configure(text="")
            self._cooldown_label.configure(text="", fg=self.root.cget("bg"))
        else:
            self._level_label.configure(text=f"{reading.dbfs:.1f} dBFS")
            over_threshold = reading.dbfs >= reading.threshold_dbfs
            self._canvas.itemconfigure(
                self._bar,
                fill=BAR_OVER_THRESHOLD_FILL if over_threshold else BAR_FILL,
            )
            level_x = max(0, min(BAR_WIDTH, _meter_x(reading.dbfs)))
            self._canvas.coords(self._bar, 0, 0, level_x, BAR_HEIGHT)
            threshold_x = max(0, min(BAR_WIDTH, _meter_x(reading.threshold_dbfs)))
            self._canvas.coords(
                self._threshold_marker, threshold_x, 0, threshold_x, BAR_HEIGHT
            )
            self._threshold_label.configure(
                text=f"Threshold: {reading.threshold_dbfs:.1f} dBFS"
            )
            if reading.cooldown_remaining_s > 0:
                self._cooldown_label.configure(
                    text=f"Cooldown: {reading.cooldown_remaining_s:.0f}s remaining",
                    fg=COOLDOWN_ACTIVE_FG,
                )
            else:
                self._cooldown_label.configure(text="Ready", fg=COOLDOWN_READY_FG)

        if self.root is not None:
            self._after_id = self.root.after(REFRESH_MS, self._refresh)

    def _close(self) -> None:
        if self.root is not None and self._after_id is not None:
            self.root.after_cancel(self._after_id)
        if self.root is not None:
            self.root.destroy()
