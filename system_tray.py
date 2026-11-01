"""System tray integration and Windows startup management.

Provides:
- TrayIcon: runs pystray in a background thread, supports Show/Exit menu.
- StartupManager: adds/removes the application from the Windows registry
  run key (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run), with a
  mockable registry backend for tests.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from typing import Callable

import pystray
from PIL import Image, ImageDraw


class StartupManager:
    """Manages Windows registry autostart entry for the application."""

    REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    VALUE_NAME = "TaskReminder"

    def __init__(self, app_path: str | Path, registry_backend: Any | None = None) -> None:
        self.app_path = str(Path(app_path).resolve())
        self._registry = registry_backend

    def _open_registry(self) -> Any:
        if self._registry is not None:
            return self._registry.OpenKey(
                None, self.REG_KEY, 0, 0
            )
        import winreg

        return winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            self.REG_KEY,
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE | winreg.KEY_DELETE,
        )

    def _close_key(self, key: Any) -> None:
        close = getattr(key, "Close", None)
        if callable(close):
            close()

    def is_enabled(self) -> bool:
        key = self._open_registry()
        try:
            value, _ = self._registry.QueryValueEx(key, self.VALUE_NAME)
            return value == self.app_path
        except Exception:
            return False
        finally:
            self._close_key(key)

    def enable(self) -> None:
        key = self._open_registry()
        try:
            if self._registry is None:
                import winreg

                winreg.SetValueEx(
                    key, self.VALUE_NAME, 0, winreg.REG_SZ, self.app_path
                )
            else:
                self._registry.SetValueEx(
                    key, self.VALUE_NAME, 0, 1, self.app_path
                )
        finally:
            self._close_key(key)

    def disable(self) -> None:
        key = self._open_registry()
        try:
            if self._registry is None:
                import winreg

                try:
                    winreg.DeleteValue(key, self.VALUE_NAME)
                except FileNotFoundError:
                    pass
            else:
                self._registry.DeleteValue(key, self.VALUE_NAME)
        finally:
            self._close_key(key)

    # ------------------------------------------------------------------
    # TrayIcon
    # ------------------------------------------------------------------


class TrayIcon:
    """System tray icon with Show and Exit menu items."""

    def __init__(
        self,
        on_show: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self.on_show = on_show
        self.on_exit = on_exit
        self.icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None

    def _create_image(self) -> Image.Image:
        width = 64
        height = 64
        image = Image.new("RGB", (width, height), "white")
        dc = ImageDraw.Draw(image)
        dc.rectangle([0, 0, width, height], fill="#e44332")
        dc.text((width // 2 - 10, height // 2 - 14), "T", fill="white")
        return image

    def _setup_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Показать окно", self._show),
            pystray.MenuItem("Выход", self._exit),
        )

    def _show(self, _icon: pystray.Icon) -> None:
        self.on_show()

    def _exit(self, _icon: pystray.Icon) -> None:
        self.on_exit()
        if self.icon is not None:
            self.icon.stop()

    def _run(self) -> None:
        self.icon = pystray.Icon(
            "task_reminder",
            self._create_image(),
            "Task Reminder",
            menu=self._setup_menu(),
        )
        self.icon.run()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.icon is not None:
            self.icon.stop()
        if self._thread is not None:
            self._thread.join(timeout=2)


class TrayController:
    """Wires the tray icon to a Tkinter window."""

    def __init__(self, root: tk.Tk, on_exit: Callable[[], None]) -> None:
        self.root = root
        self.on_exit = on_exit
        self.tray = TrayIcon(on_show=self.show_window, on_exit=self.exit_app)

    def start(self) -> None:
        self.tray.start()

    def stop(self) -> None:
        self.tray.stop()

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def hide_window(self) -> None:
        self.root.withdraw()

    def exit_app(self) -> None:
        self.on_exit()

    def on_close_button(self) -> None:
        """Call this from WM_DELETE_WINDOW to hide instead of close."""
        self.hide_window()
