"""Date and time picker using tkcalendar.

DateTimePicker opens a popup with a calendar. Clicking a date opens a
secondary time selection dialog. The selected local datetime is returned
and can be converted to UTC before saving to the database.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime, timedelta, timezone
from tkinter import ttk
from typing import Callable

from tkcalendar import Calendar


class DateTimePicker:
    """Popup calendar + time picker returning a timezone-aware local datetime."""

    def __init__(self, parent: tk.Widget) -> None:
        self.parent = parent
        self.result: datetime | None = None

    def ask(self, initial: datetime | None = None) -> datetime | None:
        """Show the calendar popup and return the selected local datetime."""
        self.result = None
        self.top = tk.Toplevel(self.parent)
        self.top.title("Выберите дату и время")
        self.top.transient(self.parent)
        self.top.grab_set()

        now = datetime.now()
        if initial is None:
            initial = now

        self.calendar = Calendar(
            self.top,
            selectmode="day",
            year=initial.year,
            month=initial.month,
            day=initial.day,
            locale="ru_RU",
            cursor="hand1",
        )
        self.calendar.pack(padx=10, pady=10)
        self.calendar.bind("<<CalendarSelected>>", self._on_date_selected)
        self.calendar.bind("<MouseWheel>", self._on_mousewheel)
        self.calendar.bind("<Button-4>", self._on_mousewheel)
        self.calendar.bind("<Button-5>", self._on_mousewheel)

        btn_frame = ttk.Frame(self.top)
        btn_frame.pack(pady=5)
        ttk.Button(btn_frame, text="Отмена", command=self.top.destroy).pack(
            side=tk.LEFT, padx=5
        )

        self.parent.wait_window(self.top)
        return self.result

    def _on_mousewheel(self, event: tk.Event) -> None:  # type: ignore[misc]
        """Scroll calendar months with mouse wheel."""
        if event.num == 4 or (event.delta and event.delta > 0):
            self.calendar._prev_month()
        elif event.num == 5 or (event.delta and event.delta < 0):
            self.calendar._next_month()

    def _on_date_selected(self, _event: tk.Event) -> None:  # type: ignore[misc]
        date = self.calendar.selection_get()
        self.top.destroy()
        time_picker = TimePicker(self.parent, date)
        self.result = time_picker.ask()
        return None


class TimePicker:
    """Popup for selecting hours and minutes."""

    MINUTES = [f"{m:02d}" for m in range(0, 60, 5)]

    def __init__(self, parent: tk.Widget, date: datetime) -> None:
        self.parent = parent
        self.date = date
        self.result: datetime | None = None

    def ask(self) -> datetime | None:
        self.top = tk.Toplevel(self.parent)
        self.top.title("Выберите время")
        self.top.transient(self.parent)
        self.top.grab_set()

        ttk.Label(self.top, text="Часы:").grid(row=0, column=0, padx=5, pady=5)
        self.hours = ttk.Combobox(
            self.top, values=[f"{h:02d}" for h in range(24)], width=5
        )
        self.hours.set("12")
        self.hours.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(self.top, text="Минуты:").grid(row=1, column=0, padx=5, pady=5)
        self.minutes = ttk.Combobox(self.top, values=self.MINUTES, width=5)
        self.minutes.set("00")
        self.minutes.grid(row=1, column=1, padx=5, pady=5)

        btn_frame = ttk.Frame(self.top)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Сохранить", command=self._save).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(btn_frame, text="Отмена", command=self.top.destroy).pack(
            side=tk.LEFT, padx=5
        )

        self.parent.wait_window(self.top)
        return self.result

    def _save(self) -> None:
        try:
            hour = int(self.hours.get())
            minute = int(self.minutes.get())
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            return

        local_dt = self.date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        local_dt = local_dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
        self.result = local_dt
        self.top.destroy()


def local_to_utc(local_dt: datetime) -> datetime:
    """Convert a timezone-aware local datetime to UTC."""
    if local_dt.tzinfo is None:
        raise ValueError("local_dt must be timezone-aware")
    return local_dt.astimezone(timezone.utc)


def utc_to_local(utc_dt: datetime) -> datetime:
    """Convert a UTC datetime to the user's local timezone."""
    if utc_dt.tzinfo is None:
        raise ValueError("utc_dt must be timezone-aware")
    return utc_dt.astimezone()


def format_local_datetime(local_dt: datetime) -> str:
    """Format a local datetime for display."""
    return local_dt.strftime("%d.%m.%Y %H:%M")


def add_minutes(utc_dt: datetime, minutes: int) -> datetime:
    """Add minutes to a UTC datetime."""
    if utc_dt.tzinfo is None:
        raise ValueError("utc_dt must be timezone-aware")
    return utc_dt + timedelta(minutes=minutes)
