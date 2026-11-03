r"""Windows startup folders: the user's always, the common one on request (0011).

One item per file; ``desktop.ini`` is the folder's settings, not an entry. The state is the
file's flag in ``Explorer\StartupApproved\StartupFolder`` of the same hive (``HKCU`` for the
user folder, ``HKLM`` for the common one), read like the Run flags (item 21). The command is
the file itself, as Explorer opens it; shortcut targets are not resolved. Read-only.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from kresorter.autostart.entries import MAX_ENTRY_BYTES, BrokenEntryError, read_entry
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
    approved_state,
    value_digest,
)

__all__ = ["MAX_ENTRY_BYTES", "STARTUP_APPROVED", "read_startup_folders", "startup_dirs"]

STARTUP_APPROVED = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
)
_PROGRAMS = Path("Microsoft", "Windows", "Start Menu", "Programs")
_SETTINGS = "desktop.ini"


def startup_dirs(env: Mapping[str, str]) -> tuple[Path | None, Path | None]:
    """The user folder and the common one; ``None`` if its variable is unset or relative."""
    return _under(env, "APPDATA", "Startup"), _under(env, "ProgramData", "StartUp")


def _under(env: Mapping[str, str], variable: str, name: str) -> Path | None:
    base = Path(env.get(variable) or ".")
    return base / _PROGRAMS / name if base.is_absolute() else None


def read_startup_folders(
    registry: Registry, user_dir: Path | None, common_dir: Path | None, *, include_machine: bool
) -> AutostartListing:
    items: list[AutostartItem] = []
    skipped: list[AutostartSkipped] = []
    folders = [(user_dir, Hive.HKCU, Scope.USER)]
    if include_machine:
        folders.append((common_dir, Hive.HKLM, Scope.SYSTEM))
    for directory, hive, scope in folders:
        if directory is not None:
            _read_folder(registry, directory, hive, scope, items, skipped)
    return AutostartListing(tuple(items), tuple(skipped))


def _read_folder(
    registry: Registry,
    directory: Path,
    hive: Hive,
    scope: Scope,
    items: list[AutostartItem],
    skipped: list[AutostartSkipped],
) -> None:
    try:
        files = _files(directory)
    except OSError as error:
        skipped.append(_skip(str(directory), f"cannot read: {error.strerror}"))
        return
    if not files:
        return  # no flags to read: an empty folder never touches the registry
    try:
        flags = registry.values(hive, STARTUP_APPROVED) or ()
    except RegistryError as error:
        skipped.append(_skip(rf"{hive}\{STARTUP_APPROVED}", f"cannot read: {error}"))
        return
    by_name = {f.name.casefold(): f for f in flags}
    for path in files:
        try:
            items.append(_item(path, hive, scope, by_name.get(path.name.casefold())))
        except BrokenEntryError as error:
            skipped.append(_skip(str(path), str(error)))


def _files(directory: Path) -> list[Path]:
    try:
        children = list(directory.iterdir())
    except FileNotFoundError:
        return []
    found = [p for p in children if p.name.casefold() != _SETTINGS]
    return sorted(found, key=lambda p: p.name.casefold())


def _skip(location: str, detail: str) -> AutostartSkipped:
    return AutostartSkipped(Source.STARTUP_FOLDER, location, detail)


def _item(path: Path, hive: Hive, scope: Scope, flag: RegValue | None) -> AutostartItem:
    raw = read_entry(path)
    enabled = approved_state(flag)
    return AutostartItem(
        source=Source.STARTUP_FOLDER,
        scope=scope,
        name=path.name,
        command=str(path),
        location=str(path),
        enabled=enabled,
        digest=value_digest(RegValue(path.name, ValueKind.REG_BINARY, raw), flag),
        notes=() if enabled else (rf"disabled in {hive}\{STARTUP_APPROVED}",),
    )
