"""``Registry`` on the real Windows registry; ``winreg`` is imported only when used (0011).

Keys are opened read-only in the 64-bit view (``KEY_READ | KEY_WOW64_64KEY``), so a path with
``WOW6432Node`` names exactly that key and nothing is redirected behind our back. A missing key
reads as ``None``; any other failure, while opening or while enumerating, is a
``RegistryError``. Only ``ERROR_NO_MORE_ITEMS`` ends the enumeration, of values and of sub-keys
alike. Writing is one value under ``HKCU`` (``KEY_SET_VALUE | KEY_WOW64_64KEY``), creating the
key if it is missing; ``HKLM`` cannot be written and nothing is ever deleted (item 80). The key
is always closed once it was opened.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Protocol, TypeVar, cast

from safeclean.autostart.registry import Hive, RegData, RegistryError, RegValue

ERROR_NO_MORE_ITEMS = 259

_T = TypeVar("_T")


class _Winreg(Protocol):
    HKEY_CURRENT_USER: int
    HKEY_LOCAL_MACHINE: int
    KEY_READ: int
    KEY_SET_VALUE: int
    KEY_WOW64_64KEY: int

    def OpenKey(self, key: int, sub_key: str, reserved: int, access: int, /) -> object: ...

    def EnumValue(self, key: object, index: int, /) -> tuple[str, object, int]: ...

    def EnumKey(self, key: object, index: int, /) -> str: ...

    def CreateKeyEx(self, key: int, sub_key: str, reserved: int, access: int, /) -> object: ...

    def SetValueEx(
        self, key: object, value_name: str, reserved: int, kind: int, value: object, /
    ) -> None: ...

    def CloseKey(self, key: object, /) -> None: ...


class WinRegistry:
    def __init__(self, module: _Winreg | None = None) -> None:
        self._module = module

    def _winreg(self) -> _Winreg:
        if self._module is None:
            self._module = cast("_Winreg", importlib.import_module("winreg"))
        return self._module

    def values(self, hive: Hive, key: str) -> list[RegValue] | None:
        return self._read(hive, key, _value)

    def subkeys(self, hive: Hive, key: str) -> list[str] | None:
        return self._read(hive, key, _subkey)

    def set_user_value(self, key: str, value: RegValue) -> None:
        winreg = self._winreg()
        access = winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY
        try:
            handle = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, access)
        except OSError as error:
            raise RegistryError(_reason(error)) from error
        try:
            winreg.SetValueEx(handle, value.name, 0, value.kind, value.data)
        except OSError as error:
            raise RegistryError(_reason(error)) from error
        finally:
            winreg.CloseKey(handle)

    def _read(
        self, hive: Hive, key: str, item: Callable[[_Winreg, object, int], _T]
    ) -> list[_T] | None:
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
            return _enumerate(lambda index: item(winreg, handle, index))
        finally:
            winreg.CloseKey(handle)


def _value(winreg: _Winreg, handle: object, index: int) -> RegValue:
    name, data, kind = winreg.EnumValue(handle, index)
    return RegValue(name, kind, cast("RegData", data))


def _subkey(winreg: _Winreg, handle: object, index: int) -> str:
    return winreg.EnumKey(handle, index)


def _enumerate(item: Callable[[int], _T]) -> list[_T]:
    found: list[_T] = []
    while True:
        try:
            found.append(item(len(found)))
        except OSError as error:
            if getattr(error, "winerror", None) == ERROR_NO_MORE_ITEMS:
                return found
            raise RegistryError(_reason(error)) from error


def _reason(error: OSError) -> str:
    return error.strerror or str(error)
