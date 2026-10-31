r"""Windows ``Run`` and ``RunOnce`` values in ``HKCU`` and, on request, ``HKLM`` (0011).

The state of a Run value is its flag in ``Explorer\StartupApproved\Run`` of the same hive, as
the Task Manager shows it: no flag is enabled, ``0x02``/``0x06`` enabled, ``0x03``/``0x07``
disabled; anything else is an unknown state and the value is skipped, never shown (item 12).
RunOnce values have no flag. ``HKLM`` is not read at all without ``include_machine``; its
32-bit view (``WOW6432Node``) is read apart, with its own flags in ``StartupApproved\Run32``,
and every item from it carries the note ``32-bit view``. Read-only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from safeclean.autostart.entries import BrokenEntryError
from safeclean.autostart.models import (
    AutostartItem,
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
)
from safeclean.autostart.registry import (
    Hive,
    Registry,
    RegistryError,
    RegValue,
    ValueKind,
    kind_name,
    value_digest,
)

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_ONCE = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
RUN_32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
RUN_ONCE_32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce"
APPROVED_32 = APPROVED + "32"
DEFAULT_NAME = "(Default)"

_STRING_KINDS = (ValueKind.REG_SZ, ValueKind.REG_EXPAND_SZ)
_ENABLED = frozenset({0x02, 0x06})
_DISABLED = frozenset({0x03, 0x07})
_SCOPES = {Hive.HKCU: Scope.USER, Hive.HKLM: Scope.SYSTEM}
_VIEW_32 = "32-bit view"


@dataclass(frozen=True)
class _View:
    """One place Run values live: the keys, their flags and the notes every item gets."""

    hive: Hive
    run: str
    run_once: str
    approved: str
    notes: tuple[str, ...] = ()


_USER = (_View(Hive.HKCU, RUN, RUN_ONCE, APPROVED),)
_MACHINE = (
    _View(Hive.HKLM, RUN, RUN_ONCE, APPROVED),
    _View(Hive.HKLM, RUN_32, RUN_ONCE_32, APPROVED_32, (_VIEW_32,)),
)


def read_run_keys(registry: Registry, *, include_machine: bool) -> AutostartListing:
    items: list[AutostartItem] = []
    skipped: list[AutostartSkipped] = []

    def add(view: _View, key: str, value: RegValue, flag: RegValue | None) -> None:
        source = Source.RUN_KEY if key == view.run else Source.RUN_ONCE_KEY
        try:
            items.append(_item(view, key, source, value, flag))
        except BrokenEntryError as error:
            skipped.append(AutostartSkipped(source, _location(view.hive, key, value), str(error)))

    def values(hive: Hive, key: str, source: Source) -> Sequence[RegValue] | None:
        """The values of ``key``; ``()`` if it does not exist, ``None`` if it cannot be read."""
        try:
            return registry.values(hive, key) or ()
        except RegistryError as error:
            skipped.append(AutostartSkipped(source, rf"{hive}\{key}", f"cannot read: {error}"))
            return None

    for view in (_USER + _MACHINE) if include_machine else _USER:
        run = values(view.hive, view.run, Source.RUN_KEY)
        flags = values(view.hive, view.approved, Source.RUN_KEY) if run else None
        if run and flags is not None:
            by_name = {f.name.casefold(): f for f in flags}
            for value in _by_name(run):
                add(view, view.run, value, by_name.get(value.name.casefold()))
        for value in _by_name(values(view.hive, view.run_once, Source.RUN_ONCE_KEY) or ()):
            add(view, view.run_once, value, None)
    return AutostartListing(tuple(items), tuple(skipped))


def _by_name(values: Sequence[RegValue]) -> list[RegValue]:
    return sorted(values, key=lambda v: v.name.casefold())


def _location(hive: Hive, key: str, value: RegValue) -> str:
    return rf"{hive}\{key}\{value.name or DEFAULT_NAME}"


def _item(
    view: _View, key: str, source: Source, value: RegValue, flag: RegValue | None
) -> AutostartItem:
    if value.kind not in _STRING_KINDS or not isinstance(value.data, str):
        raise BrokenEntryError(f"not a string value ({kind_name(value.kind)})")
    if not value.data:
        raise BrokenEntryError("empty command")
    if source is Source.RUN_ONCE_KEY:
        enabled, notes = True, (*view.notes, "runs once at the next logon")
    else:
        enabled = _state(flag)
        disabled = () if enabled else (rf"disabled in {view.hive}\{view.approved}",)
        notes = (*view.notes, *disabled)
    return AutostartItem(
        source=source,
        scope=_SCOPES[view.hive],
        name=value.name or DEFAULT_NAME,
        command=value.data,
        location=_location(view.hive, key, value),
        enabled=enabled,
        digest=value_digest(value, flag),
        notes=notes,
    )


def _state(flag: RegValue | None) -> bool:
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
