"""Start-with-Windows registration.

HKEY_CURRENT_USER, so no admin rights are needed. A machine-wide entry would
need elevation at install time, which is a worse trade for a single-user tool.
"""

from __future__ import annotations

import logging
import sys
from typing import Protocol

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "STFU"


class Registry(Protocol):
    def read(self, key: str, name: str) -> str | None: ...

    def write(self, key: str, name: str, value: str) -> None: ...

    def delete(self, key: str, name: str) -> None: ...


class WindowsRegistry:
    """The live implementation. Never exercised by automated tests."""

    def read(self, key: str, name: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                return winreg.QueryValueEx(handle, name)[0]
        except FileNotFoundError:
            return None

    def write(self, key: str, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)

    def delete(self, key: str, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE
            ) as handle:
                winreg.DeleteValue(handle, name)
        except FileNotFoundError:
            pass


class FakeRegistry:
    """In-memory registry. Part of the module's contract."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def read(self, key: str, name: str) -> str | None:
        return self.values.get((key, name))

    def write(self, key: str, name: str, value: str) -> None:
        self.values[(key, name)] = value

    def delete(self, key: str, name: str) -> None:
        self.values.pop((key, name), None)


def executable_path() -> str:
    """Where this app lives, frozen or not."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return f'"{sys.executable}" -m stfu'


def enable(command: str, registry: Registry | None = None) -> None:
    """Register `command` to run at login. Quoted, because Program Files."""
    registry = registry or WindowsRegistry()
    quoted = command if command.startswith('"') else f'"{command}"'
    registry.write(RUN_KEY, VALUE_NAME, quoted)


def disable(registry: Registry | None = None) -> None:
    registry = registry or WindowsRegistry()
    registry.delete(RUN_KEY, VALUE_NAME)


def is_enabled(registry: Registry | None = None) -> bool:
    registry = registry or WindowsRegistry()
    return registry.read(RUN_KEY, VALUE_NAME) is not None
