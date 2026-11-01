"""Tests for notification_manager.py."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from db import DatabaseManager, Task, TaskStatus
from notification_manager import (
    NotificationManager,
    NotificationOverlay,
    TelegramNotifier,
    snooze_time,
)


class DummyOverlay:
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


class DummyTelegramNotifier:
    def __init__(self, success: bool = True) -> None:
        self.success = success
        self.sent: list[Task] = []

    def send(self, task: Task) -> bool:
        self.sent.append(task)
        return self.success


class TestNotificationLogic(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.db = DatabaseManager(self.db_path)
        self.project = self.db.create_project("Project")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_overdue_task(self) -> Task:
        due = datetime.now(timezone.utc) - timedelta(hours=1)
        return self.db.create_task(self.project.id, "Overdue", due_date_utc=due)

    def test_snooze_time(self) -> None:
        due = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(
            snooze_time(due, 15),
            datetime(2026, 11, 2, 12, 15, tzinfo=timezone.utc),
        )

    def test_snooze_time_rejects_naive(self) -> None:
        with self.assertRaises(ValueError):
            snooze_time(datetime(2026, 11, 2, 12, 0), 10)

    def test_check_and_notify_finds_overdue(self) -> None:
        task = self._make_overdue_task()
        notifier = DummyTelegramNotifier(success=True)
        manager = NotificationManager(
            self.db,
            bot_token="token",
            chat_id="123",
            telegram_notifier=notifier,
            overlay_factory=DummyOverlay,
        )
        found = manager.check_and_notify()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].id, task.id)
        self.assertTrue(notifier.sent)
        updated = self.db.get_task(task.id)
        self.assertTrue(updated.is_sent)

    def test_check_and_notify_marks_sent_only_on_success(self) -> None:
        self._make_overdue_task()
        notifier = DummyTelegramNotifier(success=False)
        manager = NotificationManager(
            self.db,
            bot_token="token",
            chat_id="123",
            telegram_notifier=notifier,
            overlay_factory=DummyOverlay,
        )
        manager.check_and_notify()
        task = self.db.get_overdue_unsent_tasks()[0]
        self.assertFalse(task.is_sent)

    def test_overlay_done_updates_status(self) -> None:
        task = self._make_overdue_task()
        manager = NotificationManager(self.db, overlay_factory=DummyOverlay)
        manager._on_done(task.id)
        updated = self.db.get_task(task.id)
        self.assertEqual(updated.status, TaskStatus.DONE)

    def test_overlay_delete_removes_task(self) -> None:
        task = self._make_overdue_task()
        manager = NotificationManager(self.db, overlay_factory=DummyOverlay)
        manager._on_delete(task.id)
        with self.assertRaises(Exception):
            self.db.get_task(task.id)

    def test_overlay_snooze_updates_due_date(self) -> None:
        task = self._make_overdue_task()
        manager = NotificationManager(self.db, overlay_factory=DummyOverlay)
        manager._on_snooze(task.id, 30)
        updated = self.db.get_task(task.id)
        self.assertEqual(
            updated.due_date_utc,
            task.due_date_utc + timedelta(minutes=30),
        )
        self.assertEqual(updated.status, TaskStatus.PENDING)

    def test_overlay_timeout_marks_overdue(self) -> None:
        task = self.db.create_task(
            self.project.id,
            "Pending",
            due_date_utc=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        manager = NotificationManager(self.db, overlay_factory=DummyOverlay)
        manager._on_timeout(task.id)
        updated = self.db.get_task(task.id)
        self.assertEqual(updated.status, TaskStatus.OVERDUE)

    def test_no_notification_for_done_tasks(self) -> None:
        task = self._make_overdue_task()
        self.db.update_task(task.id, status=TaskStatus.DONE)
        notifier = DummyTelegramNotifier(success=True)
        manager = NotificationManager(
            self.db,
            telegram_notifier=notifier,
            overlay_factory=DummyOverlay,
        )
        found = manager.check_and_notify()
        self.assertEqual(len(found), 0)
        self.assertFalse(notifier.sent)


if __name__ == "__main__":
    unittest.main()
