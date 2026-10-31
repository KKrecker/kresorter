"""macOS LaunchAgents and LaunchDaemons: ``~/Library`` and ``/Library`` (0011).

launchd loads every ``*.plist`` of these directories at login (agents) or boot (daemons), so
each is an item; ``RunAtLoad`` and ``KeepAlive`` say whether it also starts then.
``/System/Library`` (the OS, protected by SIP) is not read. The state is the file's
``Disabled`` key: the overrides launchd keeps of its own are not read, and every item says so.
XML and binary property lists; strict, bounded parsing. Read-only.
"""

from __future__ import annotations

import plistlib
import shlex
from collections.abc import Mapping
from pathlib import Path

from safeclean.autostart.entries import BrokenEntryError, read_entry
from safeclean.autostart.models import (
    AutostartItem,
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
    entry_digest,
)

SUFFIX = ".plist"
FROM_FILE = "state from the file"
_DAEMON = "daemon, started at boot"


def launchd_dirs(home: Path, root: Path) -> tuple[Path, Path, Path]:
    """The user's agents, then the system's agents and daemons."""
    library = root / "Library"
    return home / "Library" / "LaunchAgents", library / "LaunchAgents", library / "LaunchDaemons"


def read_launchd(user_agents: Path, system_agents: Path, system_daemons: Path) -> AutostartListing:
    items: list[AutostartItem] = []
    skipped: list[AutostartSkipped] = []
    folders: list[tuple[Path, Scope, tuple[str, ...]]] = [
        (user_agents, Scope.USER, ()),
        (system_agents, Scope.SYSTEM, ()),
        (system_daemons, Scope.SYSTEM, (_DAEMON,)),
    ]
    for directory, scope, notes in folders:
        try:
            files = _files(directory)
        except OSError as error:
            skipped.append(_skip(directory, f"cannot read: {error.strerror}"))
            continue
        for path in files:
            try:
                items.append(_item(path, scope, notes))
            except BrokenEntryError as error:
                skipped.append(_skip(path, str(error)))
    return AutostartListing(tuple(items), tuple(skipped))


def _files(directory: Path) -> list[Path]:
    try:
        children = list(directory.iterdir())
    except FileNotFoundError:
        return []
    found = [p for p in children if p.name.endswith(SUFFIX)]
    return sorted(found, key=lambda p: p.name.casefold())


def _skip(path: Path, detail: str) -> AutostartSkipped:
    return AutostartSkipped(Source.LAUNCH_AGENT, str(path), detail)


def _item(path: Path, scope: Scope, notes: tuple[str, ...]) -> AutostartItem:
    raw = read_entry(path)
    keys = _load(raw)
    label = keys.get("Label")
    if not isinstance(label, str) or not label:
        raise BrokenEntryError("no Label")
    command = _command(keys)
    run_at_load = _boolean(keys, "RunAtLoad")
    disabled = _boolean(keys, "Disabled")
    keep_alive = keys.get("KeepAlive", False)
    if not isinstance(keep_alive, bool | dict):
        raise BrokenEntryError("KeepAlive is not a boolean or a dictionary")
    starts = _start_notes(run_at_load, keep_alive)
    return AutostartItem(
        source=Source.LAUNCH_AGENT,
        scope=scope,
        name=label,
        command=command,
        location=str(path),
        enabled=not disabled,
        digest=entry_digest(raw),
        notes=(*notes, *starts, *(("Disabled=true",) if disabled else ()), FROM_FILE),
    )


def _load(raw: bytes) -> dict[str, object]:
    """A property list (XML or binary); ``plistlib`` refuses XML entity declarations.

    ``plistlib`` is not hardened against malformed input: besides ``InvalidFileException`` it
    fails with ``ExpatError``, ``ValueError``, even ``AttributeError`` (0011, item 51). Any
    failure to parse these at most ``MAX_ENTRY_BYTES`` is therefore the same skip.
    """
    try:
        keys = plistlib.loads(raw)
    except Exception:  # see above: the input is untrusted, the failure modes are not listed
        raise BrokenEntryError("not a valid property list") from None
    if not isinstance(keys, dict):
        raise BrokenEntryError("not a dictionary")
    return keys


def _start_notes(run_at_load: bool, keep_alive: object) -> list[str]:
    notes = ["runs at load"] if run_at_load else []
    if keep_alive is True:
        notes.append("kept alive")
    elif keep_alive:
        notes.append("kept alive on conditions")
    if not run_at_load and not keep_alive:
        notes.append("loaded at login, started on demand")
    return notes


def _boolean(keys: Mapping[str, object], name: str) -> bool:
    value = keys.get(name, False)
    if not isinstance(value, bool):
        raise BrokenEntryError(f"{name} is not a boolean")
    return value


def _command(keys: Mapping[str, object]) -> str:
    """``Program`` is the executable and ``ProgramArguments`` the argv, as launchd runs them."""
    program = keys.get("Program")
    arguments = keys.get("ProgramArguments")
    if program is None and arguments is None:
        raise BrokenEntryError("no Program or ProgramArguments")
    argv: list[str] = []
    if arguments is not None:
        if not isinstance(arguments, list) or not all(isinstance(a, str) for a in arguments):
            raise BrokenEntryError("ProgramArguments is not a list of strings")
        argv = [str(a) for a in arguments]
    if program is not None:
        if not isinstance(program, str):
            raise BrokenEntryError("Program is not a string")
        argv = [program, *argv[1:]]
    if not argv or not argv[0]:
        raise BrokenEntryError("empty command")
    return shlex.join(argv)
