"""Entry point for Task Reminder.
Initializes the database, checks Telegram configuration, starts the GUI,
background notification checker, Telegram bot, and system tray.
"""
from __future__ import annotations
import ctypes
import sys
import threading
import tkinter as tk
from pathlib import Path

# Assign an AppUserModelID so Windows groups the tray icon with the app.
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TaskReminder.App.1")
except Exception:
    pass

from db import DatabaseManager
from gui import MainWindow
from notification_manager import NotificationManager
from system_tray import TrayController, create_app_icon
from telegram_bot import TelegramBot, ensure_telegram_config


class App:
    """Application lifecycle manager."""
    def __init__(self) -> None:
        # ✅ ИСПРАВЛЕНО: создаём иконку ДО всего остального
        create_app_icon()
        
        self.db = DatabaseManager("tasks.db")
        
        # ✅ ИСПРАВЛЕНО: создаём ОДНО окно Tk и передаём его в MainWindow
        self.root = tk.Tk()
        self.root.withdraw()
        
        config = ensure_telegram_config(self.db, parent=self.root)
        if config is None:
            sys.exit(0)
        
        bot_token, chat_id = config
        
        # Создаём главное окно, передавая существующий root
        self.main_window = MainWindow(self.db, self.root)
        
        self.tray_controller = TrayController(
            self.root,
            on_exit=self.shutdown,
        )
        self.tray_controller.start()
        self.root.protocol("WM_DELETE_WINDOW", self.tray_controller.on_close_button)
        
        self.notification_manager = NotificationManager(
            self.db,
            bot_token=bot_token,
            chat_id=chat_id,
        )
        self.notification_manager.start()
        
        self.telegram_bot = TelegramBot(self.db, bot_token, chat_id)
        self.telegram_bot.start()
        
        self._shutdown_event = threading.Event()

    def run(self) -> None:
        try:
            self.root.deiconify()
            self.main_window.run()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        if self._shutdown_event.is_set():
            return
        self._shutdown_event.set()
        self.notification_manager.stop()
        self.telegram_bot.stop()
        self.tray_controller.stop()
        self.root.destroy()


def main() -> None:
    app = App()
    app.run()


if __name__ == "__main__":
    main()