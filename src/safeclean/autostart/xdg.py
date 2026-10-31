"""XDG autostart entries: ``$XDG_CONFIG_HOME/autostart`` over ``$XDG_CONFIG_DIRS`` (0011).

One item per file name with its effective state. A user file replaces the first system file of
the same name (``shadows``); a user ``Hidden=true`` stub lists that system entry as disabled.
``OnlyShowIn``/``NotShowIn`` become notes. Anything unreadable is skipped with a reason; a
broken user file still replaces the system entry, whose state is then unknown. A directory
that cannot be listed is skipped with a reason, and nothing it could change is shown. Read-only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from safeclean.autostart.entries import (
    MAX_ENTRY_BYTES,
    BrokenEntryError,
    config_home,
    decode,
    read_entry,
)
from safeclean.autostart.models import (
    AutostartItem,
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
    entry_digest,
)

__all__ = ["MAX_ENTRY_BYTES", "autostart_dirs", "read_xdg"]

SUFFIX = ".desktop"
GROUP = "[Desktop Entry]"
_NOTE_KEYS = ("OnlyShowIn", "NotShowIn")
_BOOLEANS = {"true": True, "false": False}


@dataclass(frozen=True)
class _Entry:
    path: Path
    scope: Scope
    raw: bytes
    keys: dict[str, str]

    @property
    def hidden(self) -> bool:
        return self._flag("Hidden", default=False)

    @property
    def enabled(self) -> bool:
        return not self.hidden and self._flag("X-GNOME-Autostart-enabled", default=True)

    def _flag(self, key: str, *, default: bool) -> bool:
        return _BOOLEANS[self.keys[key]] if key in self.keys else default


def autostart_dirs(env: Mapping[str, str], home: Path) -> tuple[Path, tuple[Path, ...]]:
    """The user autostart directory and the system ones, most important first."""
    dirs = [Path(d) for d in env.get("XDG_CONFIG_DIRS", "").split(":") if d]
    system = [d for d in dirs if d.is_absolute()] or [Path("/etc/xdg")]
    return config_home(env, home) / "autostart", tuple(d / "autostart" for d in system)


def read_xdg(user_dir: Path, system_dirs: Sequence[Path]) -> AutostartListing:
    items: list[AutostartItem] = []
    skipped: list[AutostartSkipped] = []
    user = _files(user_dir, skipped)
    if user is None:  # a stub that cannot be seen may hide any system entry (item 32)
        return AutostartListing((), tuple(skipped))
    system, complete = _system_files(system_dirs, skipped)
    for name in sorted(user.keys() | system.keys()):
        if name not in system and not complete:
            continue  # it may be in a directory that could not be listed: `shadows` is unknown
        try:
            if name in user:
                items.append(_user_item(name, user[name], system.get(name)))
            else:
                items.append(_item(name, _load(system[name], Scope.SYSTEM)))
        except BrokenEntryError as error:
            location = user.get(name) or system[name]
            skipped.append(AutostartSkipped(Source.XDG_AUTOSTART, str(location), str(error)))
    return AutostartListing(tuple(items), tuple(skipped))


def _system_files(
    directories: Sequence[Path], skipped: list[AutostartSkipped]
) -> tuple[dict[str, Path], bool]:
    """The first file of each name, and whether every directory could be listed.

    Only directories before the first one that cannot be listed count: an entry found after it
    may be replaced by one we cannot see. The later ones are still listed, so every directory
    that cannot be listed is reported.
    """
    system: dict[str, Path] = {}
    complete = True
    for directory in directories:
        found = _files(directory, skipped)
        if found is None:
            complete = False
        elif complete:
            for name, path in found.items():
                system.setdefault(name, path)
    return system, complete


def _files(directory: Path, skipped: list[AutostartSkipped]) -> dict[str, Path] | None:
    """Entries by name: ``{}`` if missing, ``None`` and a skip if it cannot be listed."""
    try:
        children = list(directory.iterdir())
    except FileNotFoundError:
        return {}
    except OSError as error:
        detail = f"cannot read: {error.strerror}"
        skipped.append(AutostartSkipped(Source.XDG_AUTOSTART, str(directory), detail))
        return None
    return {p.name.removesuffix(SUFFIX): p for p in children if p.name.endswith(SUFFIX)}


def _user_item(name: str, path: Path, shadowed: Path | None) -> AutostartItem:
    entry = _load(path, Scope.USER, stub_allowed=True)
    if entry.hidden and "Exec" not in entry.keys:
        if shadowed is None:
            raise BrokenEntryError("Hidden=true hides no entry")
        hidden = _load(shadowed, Scope.SYSTEM)
        return _item(name, entry, command=hidden.keys["Exec"], shadows=shadowed)
    return _item(name, entry, shadows=shadowed)


def _item(
    name: str, entry: _Entry, *, command: str | None = None, shadows: Path | None = None
) -> AutostartItem:
    return AutostartItem(
        source=Source.XDG_AUTOSTART,
        scope=entry.scope,
        name=name,
        command=command or entry.keys["Exec"],
        location=str(entry.path),
        enabled=entry.enabled,
        digest=entry_digest(entry.raw),
        shadows=None if shadows is None else str(shadows),
        notes=tuple(f"{k}={entry.keys[k]}" for k in _NOTE_KEYS if k in entry.keys),
    )


def _load(path: Path, scope: Scope, *, stub_allowed: bool = False) -> _Entry:
    raw = read_entry(path)
    keys = _parse(decode(raw))
    for key in ("Hidden", "X-GNOME-Autostart-enabled"):
        if key in keys and keys[key] not in _BOOLEANS:
            raise BrokenEntryError(f"{key} is not a boolean")
    entry = _Entry(path, scope, raw, keys)
    if stub_allowed and entry.hidden:
        return entry
    if "Type" not in keys:
        raise BrokenEntryError("no Type key")
    if keys["Type"] != "Application":
        raise BrokenEntryError(f"Type is {keys['Type']}, not Application")
    if not keys.get("Exec"):
        raise BrokenEntryError("no Exec key")
    return entry


def _parse(text: str) -> dict[str, str]:
    """Keys of the ``[Desktop Entry]`` group, which must come first; later groups are ignored."""
    keys: dict[str, str] = {}
    in_group = False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not in_group:
            if stripped != GROUP:
                raise BrokenEntryError(f"no {GROUP} group")
            in_group = True
            continue
        if stripped.startswith("["):
            break
        key, sep, value = stripped.partition("=")
        if not sep:
            raise BrokenEntryError(f"malformed line {number}")
        key = key.strip()
        if key in keys:
            raise BrokenEntryError(f"duplicate key {key}")
        keys[key] = value.strip()
    if not in_group:
        raise BrokenEntryError(f"no {GROUP} group")
    return keys
