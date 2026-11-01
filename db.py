"""Database layer for Task Reminder application.

This module contains the SQLite schema and the DatabaseManager class.
All datetime values are stored and compared in UTC. Conversion to/from
local time is handled in the application layer (e.g. datetime_picker).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class TaskStatus(str, Enum):
    """Allowed task statuses."""

    PENDING = "Ожидает"
    DONE = "Готово"
    OVERDUE = "Просрочено"


class TaskLimitExceeded(Exception):
    """Raised when a project already has 10 tasks and another is added."""


class ProjectNotFound(Exception):
    """Raised when a referenced project does not exist."""


class TaskNotFound(Exception):
    """Raised when a referenced task does not exist."""


@dataclass(frozen=True)
class Project:
    id: int
    name: str
    description: str
    position: int
    created_at: datetime


@dataclass(frozen=True)
class Task:
    id: int
    project_id: int
    name: str
    description: str
    position: int
    due_date_utc: datetime
    status: TaskStatus
    is_sent: bool
    created_at: datetime


@dataclass(frozen=True)
class Attachment:
    id: int
    task_id: int
    file_path: str
    original_name: str
    created_at: datetime


class DatabaseManager:
    """Manages the SQLite database for projects, tasks and attachments."""

    MAX_TASKS_PER_PROJECT = 10

    def __init__(self, db_path: str | Path = "tasks.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def create_project(
        self,
        name: str,
        description: str = "",
        position: int | None = None,
    ) -> Project:
        if position is None:
            position = self._next_project_position()

        now = _utc_now()
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO projects (name, description, position, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (name, description, position, _format_utc(now)),
            )
            project_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()
        return self.get_project(project_id)

    def get_project(self, project_id: int) -> Project:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ProjectNotFound(f"Project {project_id} not found")
        return _row_to_project(row)

    def get_projects(self) -> list[Project]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY position ASC, created_at ASC"
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_project(row) for row in rows]

    def update_project(
        self,
        project_id: int,
        name: str | None = None,
        description: str | None = None,
        position: int | None = None,
    ) -> Project:
        fields: list[str] = []
        values: list[Any] = []
        if name is not None:
            fields.append("name = ?")
            values.append(name)
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        if position is not None:
            fields.append("position = ?")
            values.append(position)
        if not fields:
            return self.get_project(project_id)

        values.append(project_id)
        conn = self._connect()
        try:
            conn.execute(
                f"UPDATE projects SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_project(project_id)

    def delete_project(self, project_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
        finally:
            conn.close()

    def move_project_up(self, project_id: int) -> Project:
        projects = self.get_projects()
        index = next((i for i, p in enumerate(projects) if p.id == project_id), -1)
        if index <= 0:
            return projects[index]
        return self._swap_project_positions(projects[index - 1], projects[index])

    def move_project_down(self, project_id: int) -> Project:
        projects = self.get_projects()
        index = next((i for i, p in enumerate(projects) if p.id == project_id), -1)
        if index < 0 or index >= len(projects) - 1:
            return projects[index]
        return self._swap_project_positions(projects[index], projects[index + 1])

    def _swap_project_positions(self, a: Project, b: Project) -> Project:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE projects SET position = ? WHERE id = ?",
                (b.position, a.id),
            )
            conn.execute(
                "UPDATE projects SET position = ? WHERE id = ?",
                (a.position, b.id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_project(a.id)

    def _next_project_position(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM projects"
            ).fetchone()
        finally:
            conn.close()
        return row[0]

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------
    def create_task(
        self,
        project_id: int,
        name: str,
        description: str = "",
        due_date_utc: datetime | None = None,
        position: int | None = None,
        status: TaskStatus = TaskStatus.PENDING,
    ) -> Task:
        self.get_project(project_id)  # validates project exists
        task_count = self.count_tasks_in_project(project_id)
        if task_count >= self.MAX_TASKS_PER_PROJECT:
            raise TaskLimitExceeded(
                "В проекте может быть максимум 10 задач. "
                "Удалите одну из задач или создайте новый проект."
            )

        if due_date_utc is None:
            due_date_utc = _utc_now()
        if due_date_utc.tzinfo is None:
            raise ValueError("due_date_utc must be timezone-aware")
        if position is None:
            position = self._next_task_position(project_id)

        now = _utc_now()
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO tasks
                (project_id, name, description, position, due_date_utc,
                 status, is_sent, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    name,
                    description,
                    position,
                    _format_utc(due_date_utc),
                    status.value,
                    False,
                    _format_utc(now),
                ),
            )
            task_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()
        return self.get_task(task_id)

    def get_task(self, task_id: int) -> Task:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise TaskNotFound(f"Task {task_id} not found")
        return _row_to_task(row)

    def get_tasks_by_project(
        self,
        project_id: int,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        query = "SELECT * FROM tasks WHERE project_id = ?"
        params: list[Any] = [project_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY position ASC, created_at ASC"
        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        return [_row_to_task(row) for row in rows]

    def count_tasks_in_project(self, project_id: int) -> int:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        finally:
            conn.close()
        return row[0]

    def update_task(
        self,
        task_id: int,
        name: str | None = None,
        description: str | None = None,
        due_date_utc: datetime | None = None,
        position: int | None = None,
        status: TaskStatus | None = None,
        is_sent: bool | None = None,
    ) -> Task:
        fields: list[str] = []
        values: list[Any] = []
        if name is not None:
            fields.append("name = ?")
            values.append(name)
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        if due_date_utc is not None:
            if due_date_utc.tzinfo is None:
                raise ValueError("due_date_utc must be timezone-aware")
            fields.append("due_date_utc = ?")
            values.append(_format_utc(due_date_utc))
        if position is not None:
            fields.append("position = ?")
            values.append(position)
        if status is not None:
            fields.append("status = ?")
            values.append(status.value)
        if is_sent is not None:
            fields.append("is_sent = ?")
            values.append(is_sent)
        if not fields:
            return self.get_task(task_id)

        values.append(task_id)
        conn = self._connect()
        try:
            conn.execute(
                f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_task(task_id)

    def delete_task(self, task_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
        finally:
            conn.close()

    def move_task_up(self, task_id: int) -> Task:
        task = self.get_task(task_id)
        tasks = self.get_tasks_by_project(task.project_id)
        index = next((i for i, t in enumerate(tasks) if t.id == task_id), -1)
        if index <= 0:
            return tasks[index]
        return self._swap_task_positions(tasks[index - 1], tasks[index])

    def move_task_down(self, task_id: int) -> Task:
        task = self.get_task(task_id)
        tasks = self.get_tasks_by_project(task.project_id)
        index = next((i for i, t in enumerate(tasks) if t.id == task_id), -1)
        if index < 0 or index >= len(tasks) - 1:
            return tasks[index]
        return self._swap_task_positions(tasks[index], tasks[index + 1])

    def _swap_task_positions(self, a: Task, b: Task) -> Task:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE tasks SET position = ? WHERE id = ?",
                (b.position, a.id),
            )
            conn.execute(
                "UPDATE tasks SET position = ? WHERE id = ?",
                (a.position, b.id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_task(a.id)

    def _next_task_position(self, project_id: int) -> int:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM tasks WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        finally:
            conn.close()
        return row[0]

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------
    def get_tasks_for_today(self, project_id: int | None = None) -> list[Task]:
        start, end = _day_bounds(_utc_now())
        return self._get_tasks_in_range(start, end, project_id)

    def get_tasks_for_tomorrow(self, project_id: int | None = None) -> list[Task]:
        from datetime import timedelta

        tomorrow = _utc_now() + timedelta(days=1)
        start, end = _day_bounds(tomorrow)
        return self._get_tasks_in_range(start, end, project_id)

    def get_tasks_for_date(
        self,
        date_utc: datetime,
        project_id: int | None = None,
    ) -> list[Task]:
        start, end = _day_bounds(date_utc)
        return self._get_tasks_in_range(start, end, project_id)

    def _get_tasks_in_range(
        self,
        start: datetime,
        end: datetime,
        project_id: int | None = None,
    ) -> list[Task]:
        query = (
            "SELECT * FROM tasks WHERE due_date_utc >= ? AND due_date_utc < ?"
        )
        params: list[Any] = [_format_utc(start), _format_utc(end)]
        if project_id is not None:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY due_date_utc ASC, position ASC"
        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        return [_row_to_task(row) for row in rows]

    def get_overdue_unsent_tasks(self, now_utc: datetime | None = None) -> list[Task]:
        if now_utc is None:
            now_utc = _utc_now()
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE due_date_utc <= ? AND is_sent = 0 AND status != ?
                ORDER BY due_date_utc ASC, position ASC
                """,
                (_format_utc(now_utc), TaskStatus.DONE.value),
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_task(row) for row in rows]

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------
    def add_attachment(
        self,
        task_id: int,
        file_path: str,
        original_name: str,
    ) -> Attachment:
        self.get_task(task_id)  # validates task exists
        now = _utc_now()
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO attachments (task_id, file_path, original_name, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, file_path, original_name, _format_utc(now)),
            )
            attachment_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()
        return self.get_attachment(attachment_id)

    def get_attachments_for_task(self, task_id: int) -> list[Attachment]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM attachments WHERE task_id = ? ORDER BY created_at ASC",
                (task_id,),
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_attachment(row) for row in rows]

    def get_attachment(self, attachment_id: int) -> Attachment:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM attachments WHERE id = ?",
                (attachment_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ValueError(f"Attachment {attachment_id} not found")
        return _row_to_attachment(row)

    def delete_attachment(self, attachment_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    def set_config(self, key: str, value: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO config (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()

    def get_config(self, key: str) -> str | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM config WHERE key = ?",
                (key,),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def delete_config(self, key: str) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM config WHERE key = ?", (key,))
            conn.commit()
        finally:
            conn.close()


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    due_date_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Ожидает',
    is_sent BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    original_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_utc(value: str) -> datetime:
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc)


def _day_bounds(value: datetime) -> tuple[datetime, datetime]:
    from datetime import timedelta

    start = value.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = start + timedelta(days=1)
    return start, end


def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        position=row["position"],
        created_at=_parse_utc(row["created_at"]),
    )


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        project_id=row["project_id"],
        name=row["name"],
        description=row["description"],
        position=row["position"],
        due_date_utc=_parse_utc(row["due_date_utc"]),
        status=TaskStatus(row["status"]),
        is_sent=bool(row["is_sent"]),
        created_at=_parse_utc(row["created_at"]),
    )


def _row_to_attachment(row: sqlite3.Row) -> Attachment:
    return Attachment(
        id=row["id"],
        task_id=row["task_id"],
        file_path=row["file_path"],
        original_name=row["original_name"],
        created_at=_parse_utc(row["created_at"]),
    )
