"""Enabled systemd user units: links in ``$XDG_CONFIG_HOME/systemd/user/*.wants/`` (0011).

One item per link. ``location`` is the link; the target it was enabled for (``WantedBy=``) is a
note; ``command`` is the ``ExecStart`` of the unit file the link leads to, as written (several
joined with ``"; "``). A unit masked in the same directory (a link to ``/dev/null``) is listed
as disabled. Drop-ins (``*.d/*.conf``), ``*.requires/`` and units enabled for all users
(``/etc/systemd/user``) are not read. Read-only; anything unreadable is skipped with a reason.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from kresorter.autostart.entries import BrokenEntryError, config_home, decode, read_entry
from kresorter.autostart.models import (
    AutostartItem,
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
    entry_digest,
)

WANTS = ".wants"
UNIT_TYPES = frozenset(
    {
        "automount",
        "device",
        "mount",
        "path",
        "scope",
        "service",
        "slice",
        "socket",
        "swap",
        "target",
        "timer",
    }
)


def systemd_user_dir(env: Mapping[str, str], home: Path) -> Path:
    return config_home(env, home) / "systemd" / "user"


def read_systemd_user(unit_dir: Path) -> AutostartListing:
    items: list[AutostartItem] = []
    skipped: list[AutostartSkipped] = []
    for link in _links(unit_dir):
        try:
            items.append(_item(unit_dir, link))
        except BrokenEntryError as error:
            skipped.append(AutostartSkipped(Source.SYSTEMD_USER, str(link), str(error)))
    items.sort(key=lambda i: (i.name, i.location))
    return AutostartListing(tuple(items), tuple(skipped))


def _children(directory: Path) -> list[Path]:
    try:
        return sorted(directory.iterdir())
    except OSError:
        return []


def _links(unit_dir: Path) -> list[Path]:
    wants = [d for d in _children(unit_dir) if d.name.endswith(WANTS) and d.is_dir()]
    return [
        link
        for directory in wants
        for link in _children(directory)
        if link.name.rpartition(".")[2] in UNIT_TYPES
    ]


def _item(unit_dir: Path, link: Path) -> AutostartItem:
    raw = read_entry(link)
    sections = _parse(decode(raw))
    unit_type = link.name.rpartition(".")[2]
    target = str(link.readlink()) if link.is_symlink() else ""
    notes = [f"WantedBy={link.parent.name.removesuffix(WANTS)}"]
    if unit_type == "service":
        commands = sections.get("Service", {}).get("ExecStart", [])
        if not commands:
            raise BrokenEntryError("no ExecStart in [Service]")
        command = "; ".join(commands)
    else:
        command = str(link.resolve())
        notes.append(f"not a service: {unit_type}")
    masked = _is_masked(unit_dir / link.name)
    if masked:
        notes.append("masked")
    return AutostartItem(
        source=Source.SYSTEMD_USER,
        scope=Scope.USER,
        name=link.name,
        command=command,
        location=str(link),
        enabled=not masked,
        digest=entry_digest(os.fsencode(target) + b"\0" + raw),
        notes=tuple(notes),
    )


def _is_masked(path: Path) -> bool:
    """A link to ``/dev/null`` as ``systemctl mask`` writes it, which reads so wherever the files
    are read (on Windows it would lead to ``C:\\dev\\null``), or one leading to the null device."""
    if not path.is_symlink():
        return False
    return path.readlink().as_posix() == "/dev/null" or path.resolve() == Path(os.devnull).resolve()


def _parse(text: str) -> dict[str, dict[str, list[str]]]:
    """Sections -> key -> values in order; an empty value resets the list, as systemd does."""
    sections: dict[str, dict[str, list[str]]] = {}
    current: dict[str, list[str]] | None = None
    pending = ""
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not pending and (not stripped or stripped[0] in "#;"):
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1].rstrip() + " "
            continue
        stripped, pending = pending + stripped, ""
        if stripped.startswith("[") and stripped.endswith("]"):
            current = sections.setdefault(stripped[1:-1], {})
            continue
        key, sep, value = stripped.partition("=")
        if current is None or not sep:
            raise BrokenEntryError(f"malformed line {number}")
        values = current.setdefault(key.strip(), [])
        if value.strip():
            values.append(value.strip())
        else:
            values.clear()
    return sections
