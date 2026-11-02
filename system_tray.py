"""System tray integration and Windows startup management.
Provides:
- create_app_icon(): auto-generates icon if missing
- TrayIcon: runs pystray in a background thread, supports Show/Exit menu
- TrayController: wires the tray icon to a Tkinter window
- StartupManager: adds/removes the application from Windows registry run key
"""
from __future__ import annotations
import threading
import tkinter as tk
from pathlib import Path
from typing import Any, Callable
from PIL import Image, ImageDraw

try:
    import pystray
except ImportError:
    pystray = None


def create_app_icon() -> Path:
    """Create app icon programmatically if it doesn't exist."""
    assets_dir = Path(__file__).parent / "assets"
    assets_dir.mkdir(exist_ok=True)
    
    icon_path = assets_dir / "icon.ico"
    
    if icon_path.exists():
        return icon_path
    
    # Create a 256x256 icon with Todoist-like red color
    img = Image.new('RGBA', (256, 256), (228, 67, 50, 255))
    draw = ImageDraw.Draw(img)
    
    # Draw white checkmark
    draw.polygon([(70, 140), (110, 180), (190, 90)], fill='white')
    draw.polygon([(110, 180), (130, 180), (190, 120), (170, 100)], fill='white')
    
    # Save as ICO with multiple sizes
    img.save(icon_path, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    print(f"✅ Icon created: {icon_path}")
    
    return icon_path


class TrayIcon:
    """System tray icon with Show and Exit menu items using pystray."""
    
    def __init__(
        self,
        on_show: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self.on_show = on_show
        self.on_exit = on_exit
        self.icon: Any | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
    
    def _get_icon_image(self) -> Image.Image:
        """Load or create icon image."""
        icon_path = create_app_icon()
        return Image.open(icon_path)
    
    def _run(self) -> None:
        if pystray is None:
            print("❌ pystray not installed")
            return
        
        menu = pystray.Menu(
            pystray.MenuItem("Показать окно", lambda: self.on_show()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", lambda: self.on_exit()),
        )
        
        icon_image = self._get_icon_image()
        
        self.icon = pystray.Icon(
            "Task Reminder",
            icon_image,
            menu=menu,
        )
        
        self.icon.run()
    
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        self._stop_event.set()
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)


class TrayController:
    """Wires the tray icon to a Tkinter window."""
    
    def __init__(self, root: tk.Tk, on_exit: Callable[[], None]) -> None:
        self.root =