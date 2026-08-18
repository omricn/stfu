"""The report window: when it happened, how often, and how loud."""

from __future__ import annotations

import csv
import tkinter as tk
from tkinter import filedialog, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from stfu import appicon
from stfu.logstore import LogStore
from stfu.reportdata import csv_rows, session_summary, table_rows, trigger_points

ACTION_COLOURS = {"overlay_4click": "#f0a500", "desktop_drop": "#d64545"}


class ReportWindow:
    def __init__(self, store: LogStore) -> None:
        self.store = store

    def show(self) -> None:
        sessions = self.store.sessions()
        root = tk.Tk()
        appicon.set_window_icon(root)
        root.title("S.TFU report")

        # Come to the front once, without staying pinned there. A window that
        # silently opened behind a still-showing overlay looked exactly like a
        # window that never opened at all.
        root.lift()
        root.attributes("-topmost", True)
        root.after(200, lambda: root.attributes("-topmost", False))

        root.geometry("980x680")

        top = tk.Frame(root)
        top.pack(fill="x", padx=12, pady=8)
        tk.Label(top, text="Session:").pack(side="left")

        chooser = ttk.Combobox(top, values=sessions, state="readonly", width=32)
        chooser.pack(side="left", padx=8)
        summary_label = tk.Label(top, text="")
        summary_label.pack(side="left", padx=16)

        figure = Figure(figsize=(9, 3), dpi=100)
        axes = figure.add_subplot(111)
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
            events = self.store.events_for_session(session) if session else []

            axes.clear()
            points = trigger_points(events)
            if points:
                axes.scatter(
                    [p.at for p in points],
                    [p.level_dbfs if p.level_dbfs is not None else 0 for p in points],
                    c=[ACTION_COLOURS.get(p.action, "#888888") for p in points],
                    s=60,
                )
            axes.set_ylabel("dBFS")
            axes.grid(True, alpha=0.3)
            figure.autofmt_xdate()
            canvas.draw()

            table.delete(*table.get_children())
            for row in table_rows(events):
                table.insert(
                    "",
                    "end",
                    values=(
                        row.at.strftime("%H:%M:%S"),
                        row.kind,
                        row.trigger,
                        "" if row.level_dbfs is None else f"{row.level_dbfs:.1f}",
                        "" if row.strike_index is None else row.strike_index,
                        row.action,
                    ),
                )

            info = session_summary(events)
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

        tk.Button(top, text="Export CSV", command=export).pack(side="right")
        chooser.bind("<<ComboboxSelected>>", load)
        if sessions:
            chooser.current(0)
            load()
        root.mainloop()
