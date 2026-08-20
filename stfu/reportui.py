"""The report window: when it happened, how often, and how loud."""

from __future__ import annotations

import csv
import tkinter as tk
from tkinter import filedialog, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.dates import num2date
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from stfu import appicon, theme
from stfu.clock import format_dt
from stfu.config import Config
from stfu.logstore import LogStore, for_session
from stfu.reportdata import (
    csv_rows,
    off_windows,
    session_summary,
    table_rows,
    trigger_points,
)

# Amber for the popup, red for the desktop drop -- the same accent order as
# the mark, the meter, and the splash's progress bar (see docs/BRAND.md), so
# a reader who has seen any of those already knows what these mean.
ACTION_COLOURS = {"overlay_4click": theme.AMBER, "desktop_drop": theme.RED}


def _style_axes(figure, axes) -> None:
    """Dark chart to match the rest of the window (see docs/BRAND.md).

    Re-applied after every `axes.clear()` in `load()` below -- clear() drops
    per-axes styling (facecolor, spines, tick colours) back to matplotlib's
    own default light theme, so this has to run on every redraw, not just
    once at window construction.
    """
    figure.patch.set_facecolor(theme.INK)
    axes.set_facecolor(theme.SURFACE)
    axes.tick_params(colors=theme.TEXT_DIM, labelsize=8)
    for spine in axes.spines.values():
        spine.set_color(theme.HAIRLINE)
    axes.yaxis.label.set_color(theme.TEXT_DIM)
    axes.grid(True, color=theme.HAIRLINE, alpha=0.6)


class ReportWindow:
    def __init__(
        self, master: tk.Misc, store: LogStore, config: Config | None = None
    ) -> None:
        self.master = master
        self.store = store
        # Optional so this window can still be constructed without wiring a
        # real config, as the tests do. None means 24-hour, which is what it
        # rendered before the setting existed.
        self.config = config

    def _clock(self) -> str:
        return self.config.clock_format if self.config else "24h"

    def show(self) -> None:
        sessions = self.store.sessions()
        root = tk.Toplevel(self.master)
        appicon.set_window_icon(root)
        theme.apply(root)
        root.configure(bg=theme.INK)
        root.title("S.TFU report")

        # Come to the front once, without staying pinned there. A window that
        # silently opened behind a still-showing overlay looked exactly like a
        # window that never opened at all.
        root.lift()
        root.attributes("-topmost", True)
        root.after(200, lambda: root.attributes("-topmost", False))

        root.geometry("980x680")

        top = tk.Frame(root, bg=theme.INK)
        top.pack(fill="x", padx=12, pady=8)
        tk.Label(top, text="Session:", bg=theme.INK, fg=theme.TEXT).pack(side="left")

        chooser = ttk.Combobox(top, values=sessions, state="readonly", width=32)
        chooser.pack(side="left", padx=8)
        summary_label = tk.Label(top, text="", bg=theme.INK, fg=theme.TEXT_DIM)
        summary_label.pack(side="left", padx=16)

        figure = Figure(figsize=(9, 3), dpi=100)
        axes = figure.add_subplot(111)
        _style_axes(figure, axes)
        canvas = FigureCanvasTkAgg(figure, master=root)
        canvas.get_tk_widget().pack(fill="x", padx=12)

        columns = ("time", "type", "trigger", "level", "strike", "action")
        table = ttk.Treeview(root, columns=columns, show="headings", height=14)
        for column in columns:
            table.heading(column, text=column)
            table.column(column, width=130, anchor="w")
        table.pack(fill="both", expand=True, padx=12, pady=8)

        def load(_event=None) -> None:
            session = chooser.get()
            # One read, two views. The table wants this session's events; the
            # off-hours bands below want the whole log, because their records
            # carry no session id. events_for_session() would re-read and
            # re-parse the entire JSONL to get the first of those, so read
            # once here and narrow with the same predicate it uses.
            all_events = self.store.read_all()
            events = for_session(all_events, session) if session else []

            axes.clear()
            _style_axes(figure, axes)
            points = trigger_points(events)
            if points:
                axes.scatter(
                    [p.at for p in points],
                    [p.level_dbfs if p.level_dbfs is not None else 0 for p in points],
                    c=[ACTION_COLOURS.get(p.action, theme.TEXT_DIM) for p in points],
                    s=60,
                )

            info = session_summary(events)

            # Shade the scheduled off-hours so a gap in triggers reads as
            # "the app was deliberately not listening" rather than as a dead
            # microphone or a missing log.
            #
            # Read from the whole log, not from `events`. The boundary records
            # carry whatever session was open, and during quiet hours that is
            # none, so events_for_session() -- which matches session_id by
            # equality -- never returns them. Reading the filtered list finds
            # nothing and silently defeats the reason they are logged at all.
            #
            # Clip to this session's span, so one night's view is not stretched
            # across every window ever recorded. An unterminated span -- a
            # suspend with no resume, meaning the app exited inside the window
            # -- runs to the end of this session.
            if info.first_at is not None and info.last_at is not None:
                for start, end in off_windows(all_events):
                    finish = end if end is not None else info.last_at
                    if finish < info.first_at or start > info.last_at:
                        continue
                    axes.axvspan(
                        max(start, info.first_at),
                        min(finish, info.last_at),
                        color=theme.TEXT_DIM,
                        alpha=0.18,
                        zorder=0,
                    )

            axes.set_ylabel("dBFS")
            # Formatted through clock.format_dt rather than a strftime pattern,
            # so the axis renders a 12-hour time exactly the way every other
            # surface in the app does -- "1:04 PM", not "01:04 PM". num2date
            # returns a UTC-aware value; the stored data is naive local, and
            # dropping the offset recovers it.
            axes.xaxis.set_major_formatter(
                FuncFormatter(
                    lambda value, _pos: format_dt(
                        num2date(value).replace(tzinfo=None), self._clock()
                    )
                )
            )
            figure.autofmt_xdate()
            canvas.draw()

            table.delete(*table.get_children())
            for row in table_rows(events):
                table.insert(
                    "",
                    "end",
                    values=(
                        # Baked in at load() time, not re-evaluated on
                        # redraw: if Settings changes the clock format while
                        # this window is open, the axis follows immediately
                        # but these rows keep their format until the session
                        # is reselected. Acceptable -- the alternative is
                        # rebuilding the table on a timer for a case nobody
                        # hits often.
                        format_dt(row.at, self._clock(), seconds=True),
                        row.kind,
                        row.trigger,
                        "" if row.level_dbfs is None else f"{row.level_dbfs:.1f}",
                        "" if row.strike_index is None else row.strike_index,
                        row.action,
                    ),
                )

            # info was computed earlier, right after the scatter block, so the
            # off-hours shading above could use info.first_at/last_at.
            summary_label.configure(
                text=f"{info.trigger_count} triggers"
                + (
                    f", loudest {info.loudest_dbfs:.1f} dBFS"
                    if info.loudest_dbfs is not None
                    else ""
                )
            )

        def export() -> None:
            session = chooser.get()
            if not session:
                return
            path = filedialog.asksaveasfilename(
                defaultextension=".csv", filetypes=[("CSV", "*.csv")]
            )
            if not path:
                return
            with open(path, "w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerows(
                    csv_rows(self.store.events_for_session(session))
                )

        ttk.Button(top, text="Export CSV", command=export).pack(side="right")
        chooser.bind("<<ComboboxSelected>>", load)
        if sessions:
            chooser.current(0)
            load()
