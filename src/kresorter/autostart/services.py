r"""Windows services that start automatically, read in ``HKLM`` only on request (0011).

Only Win32 services (own or shared process, per-user templates) with ``Start=2`` are autostart
entries; drivers, per-user instances, keys without ``Type``, manual and disabled services are
not, and are not listed. The command is ``ImagePath`` as written (``REG_EXPAND_SZ`` kept
unexpanded); for a ``svchost`` service that is the host, not the DLL it runs. Read-only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from kresorter.autostart.entries import BrokenEntryError
from kresorter.autostart.models import (
    AutostartItem,
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
)
from kresorter.autostart.registry import (
    Hive,
    Registry,
    RegistryError,
    RegValue,
    ValueKind,
    kind_name,
    value_digest,
)

SERVICES = r"SYSTEM\CurrentControlSet\Services"

_DRIVERS = frozenset({0x1, 0x2, 0x4, 0x8})
_OWN, _SHARED, _USER, _INSTANCE, _INTERACTIVE = 0x10, 0x20, 0x40, 0x80, 0x100
_KNOWN_BITS = _OWN | _SHARED | _USER | _INSTANCE | _INTERACTIVE
_TYPE_NOTES = ((_SHARED, "shared process"), (_USER, "per-user service template"))
_AUTOMATIC = 2
_NOT_AUTOSTART = frozenset({3, 4})  # manual, disabled
_DRIVER_STARTS = frozenset({0, 1})  # boot, system
_STRING_KINDS = (ValueKind.REG_SZ, ValueKind.REG_EXPAND_SZ)


def read_services(registry: Registry, *, include_machine: bool) -> AutostartListing:
    if not include_machine:
        return AutostartListing((), ())
    try:
        names = registry.subkeys(Hive.HKLM, SERVICES) or ()
    except RegistryError as error:
        return AutostartListing((), (_skip(rf"HKLM\{SERVICES}", f"cannot read: {error}"),))
    items: list[AutostartItem] = []
    skipped: list[AutostartSkipped] = []
    for name in sorted(names, key=str.casefold):
        key = rf"{SERVICES}\{name}"
        try:
            item = _item(name, rf"HKLM\{key}", registry.values(Hive.HKLM, key) or ())
        except RegistryError as error:
            skipped.append(_skip(rf"HKLM\{key}", f"cannot read: {error}"))
        except BrokenEntryError as error:
            skipped.append(_skip(rf"HKLM\{key}", str(error)))
        else:
            if item is not None:
                items.append(item)
    return AutostartListing(tuple(items), tuple(skipped))


def _skip(location: str, detail: str) -> AutostartSkipped:
    return AutostartSkipped(Source.SERVICE, location, detail)


def _item(name: str, location: str, values: Sequence[RegValue]) -> AutostartItem | None:
    """The item of an automatic Win32 service; ``None`` for anything that is not autostart."""
    by_name = {v.name.casefold(): v for v in values}
    kind = _service_type(by_name)
    if kind is None or not _automatic(by_name):
        return None
    image = _image_path(by_name)
    delayed = by_name.get("delayedautostart")
    notes = [note for bit, note in _TYPE_NOTES if kind & bit]
    if delayed is not None and _dword(delayed, "DelayedAutostart"):
        notes.append("delayed start")
    return AutostartItem(
        source=Source.SERVICE,
        scope=Scope.SYSTEM,
        name=name,
        command=str(image.data),
        location=location,
        enabled=True,
        digest=value_digest(by_name["type"], by_name["start"], image, delayed),
        notes=tuple(notes),
    )


def _service_type(by_name: Mapping[str, RegValue]) -> int | None:
    """The ``Type`` of a Win32 service; ``None`` for a driver, an instance or no ``Type``."""
    value = by_name.get("type")
    if value is None:
        return None
    kind = _dword(value, "Type")
    if kind in _DRIVERS:
        return None
    if not kind & (_OWN | _SHARED) or kind & ~_KNOWN_BITS:
        raise BrokenEntryError(f"unknown service type 0x{kind:x}")
    return None if kind & _INSTANCE else kind


def _automatic(by_name: Mapping[str, RegValue]) -> bool:
    value = by_name.get("start")
    if value is None:
        raise BrokenEntryError("no Start value")
    start = _dword(value, "Start")
    if start in _DRIVER_STARTS:
        raise BrokenEntryError(f"start type {start} is for drivers only")
    if start != _AUTOMATIC and start not in _NOT_AUTOSTART:
        raise BrokenEntryError(f"unknown start type {start}")
    return start == _AUTOMATIC


def _image_path(by_name: Mapping[str, RegValue]) -> RegValue:
    value = by_name.get("imagepath")
    if value is None:
        raise BrokenEntryError("no ImagePath value")
    if value.kind not in _STRING_KINDS or not isinstance(value.data, str):
        raise BrokenEntryError(f"ImagePath is not a string value ({kind_name(value.kind)})")
    if not value.data:
        raise BrokenEntryError("empty command")
    return value


def _dword(value: RegValue, name: str) -> int:
    if value.kind != ValueKind.REG_DWORD or not isinstance(value.data, int):
        raise BrokenEntryError(f"{name} is not a DWORD")
    return value.data
