"""Tests for system_tray.py startup registry logic."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from system_tray import StartupManager


class FakeRegistryKey:
    """In-memory registry key for testing."""

    def __init__(self) -> None:
        self.values: dict[str, tuple[Any, int, str]] = {}

    def QueryValueEx(self, key: Any, name: str) -> tuple[str, int]:
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name][2], self.values[name][1]

    def SetValueEx(self, key: Any, name: str, reserved: int, kind: int, value: str) -> None:
        self.values[name] = (key, kind, value)

    def DeleteValue(self, key: Any, name: str) -> None:
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class FakeRegistry:
    """Wraps FakeRegistryKey as a module-like backend."""

    def __init__(self) -> None:
        self.key = FakeRegistryKey()

    def OpenKey(self, *args: Any, **kwargs: Any) -> FakeRegistryKey:
        return self.key

    def QueryValueEx(self, key: FakeRegistryKey, name: str) -> tuple[str, int]:
        return key.QueryValueEx(key, name)

    def SetValueEx(self, key: FakeRegistryKey, name: str, reserved: int, kind: int, value: str) -> None:
        key.SetValueEx(key, name, reserved, kind, value)

    def DeleteValue(self, key: FakeRegistryKey, name: str) -> None:
        try:
            key.DeleteValue(key, name)
        except FileNotFoundError:
            pass


class TestStartupManager(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.app_path = Path(self.tmp.name) / "main.py"
        self.app_path.write_text("# dummy")
        self.registry = FakeRegistry()
        self.manager = StartupManager(str(self.app_path), registry_backend=self.registry)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_enable_adds_registry_value(self) -> None:
        self.manager.enable()
        self.assertTrue(self.manager.is_enabled())
        self.assertEqual(
            self.registry.key.values[StartupManager.VALUE_NAME][2],
            str(self.app_path),
        )

    def test_disable_removes_registry_value(self) -> None:
        self.manager.enable()
        self.assertTrue(self.manager.is_enabled())
        self.manager.disable()
        self.assertFalse(self.manager.is_enabled())

    def test_is_enabled_false_when_missing(self) -> None:
        self.assertFalse(self.manager.is_enabled())

    def test_disable_when_missing_does_not_raise(self) -> None:
        self.manager.disable()
        self.assertFalse(self.manager.is_enabled())


if __name__ == "__main__":
    unittest.main()
