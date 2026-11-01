"""Notification system: Windows Overlay and Telegram integration.

NotificationManager runs a background thread that checks the database every
60 seconds for overdue unsent tasks and dispatches notifications.

NotificationOverlay is a topmost Tkinter popup with actions:
- Mark done
- Delete
- Snooze (5/10/15/30/60 minutes)
The popup auto-closes after 1 minute and marks the task as overdue.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from datetime import datetime, timedelta, timezone
from tkinter import ttk
from typing import Callable

from db import DatabaseManager, Task, TaskStatus


class NotificationOverlay:
    """Topmost Tkinter overlay for a single task notification."""

    AUTO_CLOSE_SECONDS = 60
    SNOOZE_OPTIONS = [5, 10, 15, 30, 60]

    def __init__(
        self,
        task: Task,
        on_done: Callable[[int], None],
        on_delete: Callable[[int], None],
        on_snooze: Callable[[int, int], None],
        on_close: Callable[[int], None],
    ) -> None:
        self.task = task
        self.on_done = on_done
        self.on_delete = on_delete
        self.on_snooze = on_snooze
        self.on_close = on_close
        self.closed_by_action = False
        self._after_id: str | None = None

        self.root = tk.Toplevel()
        self.root.title("Напоминание")
        self.root.attributes("-topmost", True)
        self.root.geometry("400x220")
        self.root.protocol("WM_DELETE_WINDOW", self._on_timeout)

        ttk.Label(
            self.root,
            text=task.name,
            font=("Segoe UI", 14, "bold"),
        ).pack(pady=10)

        ttk.Label(
            self.root,
            text=task.description or "Без описания",
            wraplength=360,
        ).pack(pady=5)

        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(pady=10)
        ttk.Button(
            btn_frame,
            text="✅ Готово",
            command=self._done,
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            btn_frame,
            text="🗑 Удалить",
            command=self._delete,
        ).pack(side=tk.LEFT, padx=5)

        snooze_frame = ttk.Frame(self.root)
        snooze_frame.pack(pady=10)
        ttk.Label(snooze_frame, text="Отложить:").pack(side=tk.LEFT, padx=5)
        self.snooze_var = tk.StringVar(value=str(self.SNOOZE_OPTIONS[0]))
        snooze_combo = ttk.Combobox(
            snooze_frame,
            textvariable=self.snooze_var,
            values=[f"{m} мин" for m in self.SNOOZE_OPTIONS],
            width=10,
            state="readonly",
        )
        snooze_combo.pack(side=tk.LEFT, padx=5)
        ttk.Button(
            snooze_frame,
            text="⏳ Отложить",
            command=self._snooze,
        ).pack(side=tk.LEFT, padx=5)

        self._after_id = self.root.after(
            self.AUTO_CLOSE_SECONDS * 1000, self._on_timeout
        )

    def _done(self) -> None:
        self._cancel_timeout()
        self.closed_by_action = True
        self.on_done(self.task.id)
        self.root.destroy()

    def _delete(self) -> None:
        self._cancel_timeout()
        self.closed_by_action = True
        self.on_delete(self.task.id)
        self.root.destroy()

    def _snooze(self) -> None:
        self._cancel_timeout()
        self.closed_by_action = True
        selected = self.snooze_var.get()
        minutes = int(selected.split()[0])
        self.on_snooze(self.task.id, minutes)
        self.root.destroy()

    def _on_timeout(self) -> None:
        self._cancel_timeout()
        if not self.closed_by_action:
            self.on_close(self.task.id)
        self.root.destroy()

    def _cancel_timeout(self) -> None:
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None


class TelegramNotifier:
    """Sends notifications via Telegram Bot API.

    The send method returns True only when the Telegram API confirms delivery.
    """

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, task: Task) -> bool:
        """Send a message. Returns True on confirmed success."""
        try:
            from telegram import Bot

            bot = Bot(token=self.bot_token)
            text = f"⏰ Напоминание: {task.name}"
            if task.description:
                text += f"\n{task.description}"
            response = bot.send_message(chat_id=self.chat_id, text=text)
            return response.message_id is not None
        except Exception:
            return False


class NotificationManager:
    """Background checker and dispatcher for overdue task notifications."""

    CHECK_INTERVAL_SECONDS = 60

    def __init__(
        self,
        db: DatabaseManager,
        bot_token: str | None = None,
        chat_id: str | None = None,
        telegram_notifier: TelegramNotifier | None = None,
        overlay_factory: Callable[[Task, Callable[[int], None], Callable[[int], None], Callable[[int, int], None], Callable[[int], None]], NotificationOverlay] | None = None,
    ) -> None:
        self.db = db
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.telegram_notifier = telegram_notifier
        self.overlay_factory = overlay_factory or NotificationOverlay
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.check_and_notify()
            time.sleep(self.CHECK_INTERVAL_SECONDS)

    def check_and_notify(self, now_utc: datetime | None = None) -> list[Task]:
        """Find overdue tasks and dispatch notifications."""
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        tasks = self.db.get_overdue_unsent_tasks(now_utc)
        for task in tasks:
            self._notify(task)
        return tasks

    def _notify(self, task: Task) -> None:
        self._show_overlay(task)
        telegram_ok = self._send_telegram(task)
        if telegram_ok:
            self.db.update_task(task.id, is_sent=True)

    def _show_overlay(self, task: Task) -> None:
        self.overlay_factory(
            task,
            on_done=self._on_done,
            on_delete=self._on_delete,
            on_snooze=self._on_snooze,
            on_close=self._on_timeout,
        )

    def _send_telegram(self, task: Task) -> bool:
        if self.telegram_notifier is None:
            return False
        if not self.bot_token or not self.chat_id:
            return False
        return self.telegram_notifier.send(task)

    def _on_done(self, task_id: int) -> None:
        self.db.update_task(task_id, status=TaskStatus.DONE)

    def _on_delete(self, task_id: int) -> None:
        self.db.delete_task(task_id)

    def _on_snooze(self, task_id: int, minutes: int) -> None:
        task = self.db.get_task(task_id)
        new_due = task.due_date_utc + timedelta(minutes=minutes)
        self.db.update_task(task_id, due_date_utc=new_due, status=TaskStatus.PENDING)

    def _on_timeout(self, task_id: int) -> None:
        self.db.update_task(task_id, status=TaskStatus.OVERDUE)


def snooze_time(due_date_utc: datetime, minutes: int) -> datetime:
    """Add snooze minutes to a UTC due date."""
    if due_date_utc.tzinfo is None:
        raise ValueError("due_date_utc must be timezone-aware")
    return due_date_utc + timedelta(minutes=minutes)
