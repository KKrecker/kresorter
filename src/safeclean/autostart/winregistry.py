"""``Registry`` on the real Windows registry; ``winreg`` is imported only when used (0011).

Keys are opened read-only in the 64-bit view (``KEY_READ | KEY_WOW64_64KEY``), so a path with
``WOW6432Node`` names exactly that key and nothing is redirected behind our back. A missing key
reads as ``None``; any other failure, while opening or while enumerating, is a
``RegistryError``. Only ``ERROR_NO_MORE_ITEMS`` ends the enumeration. The key is always closed.
"""

from __future__ import annotations

import importlib
from typing import Protocol, cast

from safeclean.autostart.registry import Hive, RegData, RegistryError, RegValue

ERROR_NO_MORE_ITEMS = 259


class _Winreg(Protocol):
    HKEY_CURRENT_USER: int
    HKEY_LOCAL_MACHINE: int
    KEY_READ: int
    KEY_WOW64_64KEY: int

    def OpenKey(self, key: int, sub_key: str, reserved: int, access: int, /) -> object: ...

    def EnumValue(self, key: object, index: int, /) -> tuple[str, object, int]: ...

    def CloseKey(self, key: object, /) -> None: ...


class WinRegistry:
    def __init__(self, module: _Winreg | None = None) -> None:
        self._module = module

    def _winreg(self) -> _Winreg:
        if self._module is None:
            self._module = cast("_Winreg", importlib.import_module("winreg"))
        return self._module

    def values(self, hive: Hive, key: str) -> list[RegValue] | None:
        winreg = self._winreg()
        root = winreg.HKEY_CURRENT_USER if hive is Hive.HKCU else winreg.HKEY_LOCAL_MACHINE
        access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        try:
            handle = winreg.OpenKey(root, key, 0, access)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise RegistryError(_reason(error)) from error
        try:
            return _enumerate(winreg, handle)
        finally:
            winreg.CloseKey(handle)


def _enumerate(winreg: _Winreg, handle: object) -> list[RegValue]:
    found: list[RegValue] = []
    while True:
        try:
            name, data, kind = winreg.EnumValue(handle, len(found))
        except OSError as error:
            if getattr(error, "winerror", None) == ERROR_NO_MORE_ITEMS:
                return found
            raise RegistryError(_reason(error)) from error
        found.append(RegValue(name, kind, cast("RegData", data)))


def _reason(error: OSError) -> str:
    return error.strerror or str(error)
