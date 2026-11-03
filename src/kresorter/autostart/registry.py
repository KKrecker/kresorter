"""A view of the Windows registry, so readers can be tested on a fake (0011, items 11, 80).

Value names are case-insensitive, as in the registry. A key that does not exist reads as
``None``, for its values and its sub-keys alike; a key that exists but cannot be read raises
``RegistryError``. ``Registry`` only reads; ``UserRegistry`` also writes one value under
``HKCU``, and nothing can write ``HKLM`` or delete anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Protocol

from kresorter.autostart.entries import BrokenEntryError
from kresorter.autostart.models import entry_digest

RegData = str | bytes | int | list[str] | None


class Hive(StrEnum):
    HKCU = "HKCU"
    HKLM = "HKLM"


class ValueKind(IntEnum):
    REG_NONE = 0
    REG_SZ = 1
    REG_EXPAND_SZ = 2
    REG_BINARY = 3
    REG_DWORD = 4
    REG_MULTI_SZ = 7
    REG_QWORD = 11


class RegistryError(Exception):
    """A key exists but cannot be read (access denied, ...); the message says why."""


@dataclass(frozen=True)
class RegValue:
    name: str  # "" is the key's default value
    kind: int  # a ValueKind, or any other type number the registry reports
    data: RegData


class Registry(Protocol):
    def values(self, hive: Hive, key: str) -> Sequence[RegValue] | None: ...

    def subkeys(self, hive: Hive, key: str) -> Sequence[str] | None:
        """Names of the keys directly below ``key``, in no particular order."""


class UserRegistry(Registry, Protocol):
    def set_user_value(self, key: str, value: RegValue) -> None:
        """Write one value under ``HKCU\\key``, creating the key if it is missing.

        There is no hive parameter: nothing in kresorter can write ``HKLM`` (0011, item 80).
        """


_KIND_NAMES = {kind.value: kind.name for kind in ValueKind}


def kind_name(kind: int) -> str:
    """``REG_*`` name of a type number; one the registry reports but we do not know by number."""
    return _KIND_NAMES.get(kind, f"type {kind}")


def value_digest(*values: RegValue | None) -> str:
    """Fingerprint of registry values as read (name, type, data); ``None`` for a missing one.

    Every field is length-prefixed, so no two different sets of values encode alike.
    """
    return entry_digest(b"".join(_field(b"") if v is None else _encode(v) for v in values))


def _encode(value: RegValue) -> bytes:
    data = value.data
    if data is None:
        parts: list[bytes] = []
    elif isinstance(data, bytes):
        parts = [data]
    elif isinstance(data, list):
        parts = [item.encode("utf-8") for item in data]
    else:
        parts = [str(data).encode("utf-8")]
    fields = [value.name.encode("utf-8"), str(value.kind).encode(), *parts]
    return _field(b"".join(_field(f) for f in fields))


def _field(raw: bytes) -> bytes:
    return len(raw).to_bytes(4, "big") + raw


_ENABLED = frozenset({0x02, 0x06})
_DISABLED = frozenset({0x03, 0x07})


def approved_state(flag: RegValue | None) -> bool:
    """The state an ``Explorer\\StartupApproved`` flag gives, as the Task Manager reads it.

    No flag is enabled, ``0x02``/``0x06`` enabled, ``0x03``/``0x07`` disabled; anything else is
    an unknown state, a ``BrokenEntryError`` (0011, items 12 and 21).
    """
    if flag is None:
        return True
    if flag.kind != ValueKind.REG_BINARY or not isinstance(flag.data, bytes):
        raise BrokenEntryError("StartupApproved value is not binary")
    if not flag.data:
        raise BrokenEntryError("unknown StartupApproved state (empty)")
    if flag.data[0] in _ENABLED:
        return True
    if flag.data[0] in _DISABLED:
        return False
    raise BrokenEntryError(f"unknown StartupApproved state 0x{flag.data[0]:02x}")
