"""Tests for attachment_manager.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from attachment_manager import (
    AttachmentLimitExceeded,
    AttachmentManager,
    FileSizeExceeded,
)
from db import DatabaseManager


class TestAttachmentManager(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.storage = Path(self.tmp.name) / "attachments"
        self.db = DatabaseManager(self.db_path)
        self.project = self.db.create_project("Project")
        self.task = self.db.create_task(self.project.id, "Task")
        self.manager = AttachmentManager(
            self.db,
            storage_path=self.storage,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_file(self, name: str, content: bytes = b"hello") -> Path:
        path = Path(self.tmp.name) / name
        path.write_bytes(content)
        return path

    def test_add_attachment_copies_file(self) -> None:
        source = self._make_file("doc.txt")
        attachment = self.manager.add_attachment(self.task.id, source)
        self.assertEqual(attachment.original_name, "doc.txt")
        self.assertTrue(Path(attachment.file_path).exists())

    def test_count_attachments(self) -> None:
        self.assertEqual(self.manager.count_attachments(self.task.id), 0)
        self.manager.add_attachment(self.task.id, self._make_file("a.txt"))
        self.assertEqual(self.manager.count_attachments(self.task.id), 1)

    def test_attachment_limit(self) -> None:
        for i in range(10):
            self.manager.add_attachment(self.task.id, self._make_file(f"{i}.txt"))
        with self.assertRaises(AttachmentLimitExceeded):
            self.manager.add_attachment(self.task.id, self._make_file("extra.txt"))

    def test_file_size_limit(self) -> None:
        source = self._make_file("big.bin", b"x" * (51 * 1024 * 1024))
        with self.assertRaises(FileSizeExceeded):
            self.manager.add_attachment(self.task.id, source)

    def test_delete_attachment_removes_file(self) -> None:
        source = self._make_file("to_delete.txt")
        attachment = self.manager.add_attachment(self.task.id, source)
        stored = Path(attachment.file_path)
        self.assertTrue(stored.exists())
        self.manager.delete_attachment(attachment.id)
        self.assertFalse(stored.exists())
        self.assertEqual(len(self.db.get_attachments_for_task(self.task.id)), 0)

    def test_delete_missing_record_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.delete_attachment(999)

    def test_open_missing_file_raises(self) -> None:
        source = self._make_file("missing.txt")
        attachment = self.manager.add_attachment(self.task.id, source)
        Path(attachment.file_path).unlink()
        with self.assertRaises(FileNotFoundError):
            self.manager.open_attachment(attachment.id)


if __name__ == "__main__":
    unittest.main()
