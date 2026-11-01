"""TDD tests for DatabaseManager."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from db import (
    Attachment,
    DatabaseManager,
    Project,
    Task,
    TaskLimitExceeded,
    TaskNotFound,
    TaskStatus,
)


class TestDatabaseManager(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.db = DatabaseManager(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ------------------------------------------------------------------
    # Project CRUD
    # ------------------------------------------------------------------
    def test_create_and_get_project(self) -> None:
        project = self.db.create_project("Work", "Work tasks")
        self.assertIsInstance(project, Project)
        self.assertEqual(project.name, "Work")
        self.assertEqual(project.description, "Work tasks")
        self.assertEqual(project.position, 1)

    def test_get_projects_ordered_by_position(self) -> None:
        p1 = self.db.create_project("B", position=2)
        p2 = self.db.create_project("A", position=1)
        projects = self.db.get_projects()
        self.assertEqual([p.id for p in projects], [p2.id, p1.id])

    def test_update_project(self) -> None:
        project = self.db.create_project("Old")
        updated = self.db.update_project(
            project.id, name="New", description="Updated"
        )
        self.assertEqual(updated.name, "New")
        self.assertEqual(updated.description, "Updated")

    def test_delete_project(self) -> None:
        project = self.db.create_project("To delete")
        self.db.delete_project(project.id)
        with self.assertRaises(Exception):
            self.db.get_project(project.id)

    def test_move_project_up_and_down(self) -> None:
        p1 = self.db.create_project("First", position=1)
        p2 = self.db.create_project("Second", position=2)
        self.db.move_project_down(p1.id)
        projects = self.db.get_projects()
        self.assertEqual([p.id for p in projects], [p2.id, p1.id])

        self.db.move_project_up(p1.id)
        projects = self.db.get_projects()
        self.assertEqual([p.id for p in projects], [p1.id, p2.id])

    # ------------------------------------------------------------------
    # Task CRUD and limit
    # ------------------------------------------------------------------
    def test_create_task(self) -> None:
        project = self.db.create_project("Project")
        due = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        task = self.db.create_task(
            project.id, "Task", "Description", due_date_utc=due
        )
        self.assertIsInstance(task, Task)
        self.assertEqual(task.name, "Task")
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertEqual(task.due_date_utc, due)

    def test_task_limit(self) -> None:
        project = self.db.create_project("Limited")
        for i in range(DatabaseManager.MAX_TASKS_PER_PROJECT):
            self.db.create_task(project.id, f"Task {i}")
        with self.assertRaises(TaskLimitExceeded):
            self.db.create_task(project.id, "Too many")

    def test_count_tasks_in_project(self) -> None:
        project = self.db.create_project("Count")
        for i in range(3):
            self.db.create_task(project.id, f"Task {i}")
        self.assertEqual(self.db.count_tasks_in_project(project.id), 3)

    def test_naive_datetime_rejected(self) -> None:
        project = self.db.create_project("Project")
        naive = datetime(2026, 11, 2, 12, 0)
        with self.assertRaises(ValueError):
            self.db.create_task(project.id, "Bad", due_date_utc=naive)

    # ------------------------------------------------------------------
    # Task ordering
    # ------------------------------------------------------------------
    def test_move_task_up_and_down(self) -> None:
        project = self.db.create_project("Project")
        t1 = self.db.create_task(project.id, "First", position=1)
        t2 = self.db.create_task(project.id, "Second", position=2)
        self.db.move_task_down(t1.id)
        tasks = self.db.get_tasks_by_project(project.id)
        self.assertEqual([t.id for t in tasks], [t2.id, t1.id])

        self.db.move_task_up(t1.id)
        tasks = self.db.get_tasks_by_project(project.id)
        self.assertEqual([t.id for t in tasks], [t1.id, t2.id])

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------
    def test_get_tasks_for_today(self) -> None:
        project = self.db.create_project("Project")
        now = datetime.now(timezone.utc)
        self.db.create_task(project.id, "Today", due_date_utc=now)
        future = now + timedelta(days=2)
        self.db.create_task(project.id, "Future", due_date_utc=future)
        today_tasks = self.db.get_tasks_for_today(project.id)
        self.assertEqual(len(today_tasks), 1)
        self.assertEqual(today_tasks[0].name, "Today")

    def test_get_tasks_for_tomorrow(self) -> None:
        project = self.db.create_project("Project")
        now = datetime.now(timezone.utc)
        tomorrow = now + timedelta(days=1)
        self.db.create_task(project.id, "Tomorrow", due_date_utc=tomorrow)
        self.db.create_task(project.id, "Today", due_date_utc=now)
        tomorrow_tasks = self.db.get_tasks_for_tomorrow(project.id)
        self.assertEqual(len(tomorrow_tasks), 1)
        self.assertEqual(tomorrow_tasks[0].name, "Tomorrow")

    def test_get_tasks_for_specific_date(self) -> None:
        project = self.db.create_project("Project")
        date_utc = datetime(2026, 11, 5, 15, 30, tzinfo=timezone.utc)
        self.db.create_task(project.id, "Dated", due_date_utc=date_utc)
        self.db.create_task(
            project.id,
            "Other",
            due_date_utc=datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc),
        )
        found = self.db.get_tasks_for_date(date_utc, project.id)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].name, "Dated")

    def test_get_overdue_unsent_tasks(self) -> None:
        project = self.db.create_project("Project")
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        task = self.db.create_task(project.id, "Overdue", due_date_utc=past)
        overdue = self.db.get_overdue_unsent_tasks()
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0].id, task.id)

        self.db.update_task(task.id, status=TaskStatus.DONE)
        overdue = self.db.get_overdue_unsent_tasks()
        self.assertEqual(len(overdue), 0)

    def test_get_overdue_skips_sent(self) -> None:
        project = self.db.create_project("Project")
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        task = self.db.create_task(project.id, "Sent", due_date_utc=past)
        self.db.update_task(task.id, is_sent=True)
        overdue = self.db.get_overdue_unsent_tasks()
        self.assertEqual(len(overdue), 0)

    # ------------------------------------------------------------------
    # UTC / Local conversion
    # ------------------------------------------------------------------
    def test_utc_local_conversion(self) -> None:
        utc_dt = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        local_dt = utc_dt.astimezone()
        self.assertEqual(local_dt.astimezone(timezone.utc), utc_dt)

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------
    def test_add_and_get_attachments(self) -> None:
        project = self.db.create_project("Project")
        task = self.db.create_task(project.id, "Task")
        attachment = self.db.add_attachment(
            task.id, "/path/to/file.txt", "file.txt"
        )
        self.assertIsInstance(attachment, Attachment)
        attachments = self.db.get_attachments_for_task(task.id)
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].original_name, "file.txt")

    def test_delete_attachment(self) -> None:
        project = self.db.create_project("Project")
        task = self.db.create_task(project.id, "Task")
        attachment = self.db.add_attachment(task.id, "/path", "name")
        self.db.delete_attachment(attachment.id)
        self.assertEqual(len(self.db.get_attachments_for_task(task.id)), 0)

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    def test_config(self) -> None:
        self.db.set_config("bot_token", "12345:token")
        self.db.set_config("chat_id", "12345")
        self.assertEqual(self.db.get_config("bot_token"), "12345:token")
        self.assertEqual(self.db.get_config("chat_id"), "12345")

    def test_delete_config(self) -> None:
        self.db.set_config("key", "value")
        self.db.delete_config("key")
        self.assertIsNone(self.db.get_config("key"))

    # ------------------------------------------------------------------
    # Deletion cascades
    # ------------------------------------------------------------------
    def test_delete_project_cascades_tasks(self) -> None:
        project = self.db.create_project("Project")
        task = self.db.create_task(project.id, "Task")
        self.db.delete_project(project.id)
        with self.assertRaises(TaskNotFound):
            self.db.get_task(task.id)


if __name__ == "__main__":
    unittest.main()
