"""Attachment manager for Task Reminder.

Handles copying files into a local ./attachments/ folder, recording metadata
in the database, opening attachments with the default application, and
cleaning up files on disk when attachments are deleted.

Limits:
- Max 50 MB per file.
- Max 10 attachments per task.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from db import Attachment, DatabaseManager


class AttachmentLimitExceeded(Exception):
    """Raised when the attachment limit for a task is exceeded."""


class FileSizeExceeded(Exception):
    """Raised when a single file exceeds the size limit."""


@dataclass(frozen=True)
class AttachmentLimits:
    max_file_size_mb: int = 50
    max_attachments_per_task: int = 10


class AttachmentManager:
    """Manages file attachments for tasks."""

    def __init__(
        self,
        db: DatabaseManager,
        storage_path: str | Path = "./attachments",
        limits: AttachmentLimits | None = None,
        file_size_func: Callable[[Path], int] | None = None,
    ) -> None:
        self.db = db
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.limits = limits or AttachmentLimits()
        self._file_size_func = file_size_func or (lambda p: p.stat().st_size)

    def count_attachments(self, task_id: int) -> int:
        return len(self.db.get_attachments_for_task(task_id))

    def add_attachment(self, task_id: int, source_path: str | Path) -> Attachment:
        """Copy a file into storage and register it in the database."""
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"File not found: {source}")

        if self.count_attachments(task_id) >= self.limits.max_attachments_per_task:
            raise AttachmentLimitExceeded(
                f"Maximum {self.limits.max_attachments_per_task} attachments per task"
            )

        file_size = self._file_size_func(source)
        max_size = self.limits.max_file_size_mb * 1024 * 1024
        if file_size > max_size:
            raise FileSizeExceeded(
                f"File exceeds {self.limits.max_file_size_mb} MB limit"
            )

        destination = self.storage_path / f"{task_id}_{source.name}"
        shutil.copy2(source, destination)

        return self.db.add_attachment(
            task_id,
            str(destination.resolve()),
            source.name,
        )

    def open_attachment(self, attachment_id: int) -> None:
        """Open the attachment with the default Windows application."""
        attachment = self.db.get_attachment(attachment_id)
        path = Path(attachment.file_path)
        if not path.exists():
            raise FileNotFoundError(f"Attachment file missing: {path}")
        os.startfile(str(path))

    def delete_attachment(self, attachment_id: int) -> None:
        """Remove the attachment record and delete the stored file."""
        attachment = self.db.get_attachment(attachment_id)
        path = Path(attachment.file_path)
        self.db.delete_attachment(attachment_id)
        if path.exists():
            path.unlink()

    def get_attachments_for_task(self, task_id: int) -> list[Attachment]:
        return self.db.get_attachments_for_task(task_id)
