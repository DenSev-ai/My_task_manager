"""Telegram bot integration with inline callback handlers.

On first start, if config lacks bot_token or chat_id, a Tkinter setup dialog
is shown. The bot runs in a background thread and handles inline buttons for
marking tasks done, deleting tasks, and snoozing tasks.
"""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import timedelta
from tkinter import messagebox, ttk
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from db import DatabaseManager, TaskStatus


class TelegramConfigDialog(tk.Toplevel):
    """Initial setup dialog for bot_token and chat_id."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self.title("Настройка Telegram")
        self.transient(parent)
        self.grab_set()
        self.result: dict[str, str] | None = None

        ttk.Label(self, text="Bot Token:").grid(row=0, column=0, padx=5, pady=5)
        self.token_entry = ttk.Entry(self, width=50)
        self.token_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(self, text="Chat ID:").grid(row=1, column=0, padx=5, pady=5)
        self.chat_entry = ttk.Entry(self, width=50)
        self.chat_entry.grid(row=1, column=1, padx=5, pady=5)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Сохранить", command=self._save).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(btn_frame, text="Отмена", command=self.destroy).pack(
            side=tk.LEFT, padx=5
        )

    def _save(self) -> None:
        token = self.token_entry.get().strip()
        chat_id = self.chat_entry.get().strip()
        if not token or not chat_id:
            messagebox.showerror("Ошибка", "Заполните оба поля")
            return
        self.result = {"bot_token": token, "chat_id": chat_id}
        self.destroy()


def ensure_telegram_config(
    db: DatabaseManager,
    parent: tk.Widget | None = None,
) -> tuple[str, str] | None:
    """Return (bot_token, chat_id), showing a dialog if missing."""
    token = db.get_config("bot_token")
    chat_id = db.get_config("chat_id")
    if token and chat_id:
        return token, chat_id

    if parent is None:
        parent = tk.Tk()
        parent.withdraw()

    dialog = TelegramConfigDialog(parent)
    parent.wait_window(dialog)
    if dialog.result is None:
        return None
    db.set_config("bot_token", dialog.result["bot_token"])
    db.set_config("chat_id", dialog.result["chat_id"])
    return dialog.result["bot_token"], dialog.result["chat_id"]


class TelegramBot:
    """Telegram bot with inline callback handlers."""

    SNOOZE_OPTIONS = [5, 10, 15, 30, 60]

    def __init__(self, db: DatabaseManager, bot_token: str, chat_id: str) -> None:
        self.db = db
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.application: Application | None = None
        self._thread: threading.Thread | None = None

    def _build_main_keyboard(self, task_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Готово", callback_data=f"done:{task_id}"
                    ),
                    InlineKeyboardButton(
                        "🗑 Удалить", callback_data=f"delete:{task_id}"
                    ),
                    InlineKeyboardButton(
                        "⏳ Отложить", callback_data=f"snooze_menu:{task_id}"
                    ),
                ]
            ]
        )

    def _build_snooze_keyboard(self, task_id: int) -> InlineKeyboardMarkup:
        buttons = [
            InlineKeyboardButton(
                f"+{m} мин", callback_data=f"snooze:{task_id}:{m}"
            )
            for m in self.SNOOZE_OPTIONS
        ]
        rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
        rows.append(
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"back:{task_id}")]
        )
        return InlineKeyboardMarkup(rows)

    async def _start_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await update.message.reply_text(
            "Бот напоминаний активирован. Ожидайте уведомлений о задачах."
        )

    async def _callback_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        await query.answer()
        data = query.data or ""
        parts = data.split(":")
        if len(parts) < 2:
            return

        action = parts[0]
        task_id = int(parts[1])

        try:
            task = self.db.get_task(task_id)
        except Exception:
            await query.edit_message_text("Задача не найдена.")
            return

        if action == "done":
            self.db.update_task(task_id, status=TaskStatus.DONE)
            await query.edit_message_text(f"✅ {task.name} — выполнено")
        elif action == "delete":
            self.db.delete_task(task_id)
            await query.edit_message_text(f"🗑 {task.name} — удалено")
        elif action == "snooze_menu":
            await query.edit_message_text(
                f"⏳ {task.name}\nВыберите время откладывания:",
                reply_markup=self._build_snooze_keyboard(task_id),
            )
        elif action == "snooze" and len(parts) == 3:
            minutes = int(parts[2])
            new_due = task.due_date_utc + timedelta(minutes=minutes)
            self.db.update_task(
                task_id,
                due_date_utc=new_due,
                status=TaskStatus.PENDING,
            )
            await query.edit_message_text(
                f"⏳ {task.name} — отложено на {minutes} минут"
            )
        elif action == "back":
            await query.edit_message_text(
                f"{task.name}",
                reply_markup=self._build_main_keyboard(task_id),
            )

    def _run(self) -> None:
        self.application = Application.builder().token(self.bot_token).build()
        self.application.add_handler(CommandHandler("start", self._start_handler))
        self.application.add_handler(CallbackQueryHandler(self._callback_handler))
        self.application.run_polling(drop_pending_updates=True)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.application is not None:
            self.application.stop()
        if self._thread is not None:
            self._thread.join(timeout=2)

    async def send_notification(self, task_name: str, task_id: int) -> bool:
        """Send a notification message with inline buttons."""
        if self.application is None:
            return False
        try:
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=f"⏰ Напоминание: {task_name}",
                reply_markup=self._build_main_keyboard(task_id),
            )
            return True
        except Exception:
            return False
