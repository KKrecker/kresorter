"""A read-only view of the Windows registry, so readers can be tested on a fake (0011, item 11).

Value names are case-insensitive, as in the registry. A key that does not exist reads as
``None``; a key that exists but cannot be read raises ``RegistryError``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Protocol

from safeclean.autostart.models import entry_digest

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


def kind_name(kind: int) -> str:
    return ValueKind(kind).name if kind in ValueKind else f"type {kind}"


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
