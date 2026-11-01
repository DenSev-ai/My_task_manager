"""Tests for telegram_bot.py callback handlers."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from telegram import InlineKeyboardMarkup

from db import DatabaseManager, TaskStatus
from telegram_bot import TelegramBot


class DummyUpdate:
    def __init__(self) -> None:
        self.callback_query = MagicMock()
        self.callback_query.answer = AsyncMock()
        self.callback_query.edit_message_text = AsyncMock()
        self.callback_query.data = ""


class DummyContext:
    pass


class TestTelegramBotCallbacks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.db = DatabaseManager(self.db_path)
        self.project = self.db.create_project("Project")
        due = datetime.now(timezone.utc) - timedelta(hours=1)
        self.task = self.db.create_task(
            self.project.id, "Test Task", due_date_utc=due
        )
        self.bot = TelegramBot(self.db, "dummy_token", "12345")

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def _run_callback(self, data: str) -> DummyUpdate:
        update = DummyUpdate()
        update.callback_query.data = data
        context = DummyContext()
        await self.bot._callback_handler(update, context)
        return update

    async def test_done_callback(self) -> None:
        await self._run_callback(f"done:{self.task.id}")
        self.assertEqual(self.db.get_task(self.task.id).status, TaskStatus.DONE)

    async def test_delete_callback(self) -> None:
        await self._run_callback(f"delete:{self.task.id}")
        with self.assertRaises(Exception):
            self.db.get_task(self.task.id)

    async def test_snooze_callback(self) -> None:
        await self._run_callback(f"snooze:{self.task.id}:15")
        updated = self.db.get_task(self.task.id)
        self.assertEqual(
            updated.due_date_utc,
            self.task.due_date_utc + timedelta(minutes=15),
        )
        self.assertEqual(updated.status, TaskStatus.PENDING)

    async def test_back_callback(self) -> None:
        update = await self._run_callback(f"back:{self.task.id}")
        calls = update.callback_query.edit_message_text.call_args_list
        self.assertTrue(calls)
        _, kwargs = calls[0]
        self.assertIsInstance(kwargs.get("reply_markup"), InlineKeyboardMarkup)

    async def test_snooze_menu_callback(self) -> None:
        update = await self._run_callback(f"snooze_menu:{self.task.id}")
        calls = update.callback_query.edit_message_text.call_args_list
        self.assertTrue(calls)
        _, kwargs = calls[0]
        self.assertIsInstance(kwargs.get("reply_markup"), InlineKeyboardMarkup)

    async def test_invalid_task(self) -> None:
        update = await self._run_callback("done:99999")
        update.callback_query.edit_message_text.assert_called_with(
            "Задача не найдена."
        )


if __name__ == "__main__":
    unittest.main()
