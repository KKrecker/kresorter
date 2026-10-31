r"""Windows scheduled tasks that start at boot or logon, read only on request (0011).

Task definitions are XML files under ``%SystemRoot%\System32\Tasks``, one per task, in
folders; they are machine-wide, so nothing is read without ``include_machine``. A task is an
autostart entry if it has a ``BootTrigger`` or a ``LogonTrigger``; tasks with other triggers
only are not listed. The command is the first action as written. Parsing is strict and
bounded, and a DTD is refused before parsing, so no entity is ever expanded. Read-only.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from xml.parsers import expat

from safeclean.autostart.entries import MAX_ENTRY_BYTES, BrokenEntryError, read_entry
from safeclean.autostart.models import (
    AutostartItem,
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
    entry_digest,
)

__all__ = ["MAX_ENTRY_BYTES", "read_tasks", "tasks_dir"]

_NS = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
_TRIGGERS = (("BootTrigger", "at boot"), ("LogonTrigger", "at logon"))
_BOOLEANS = {"true": True, "1": True, "false": False, "0": False}  # xs:boolean


@dataclass(frozen=True)
class _Found:
    name: str  # the task path, as the Task Scheduler shows it
    path: Path


def tasks_dir(env: Mapping[str, str]) -> Path | None:
    """``System32\\Tasks`` under ``%SystemRoot%`` or ``%windir%``; ``None`` if neither is usable."""
    for variable in ("SystemRoot", "windir"):
        base = Path(env.get(variable) or ".")
        if base.is_absolute():
            return base / "System32" / "Tasks"
    return None


def read_tasks(root: Path | None, *, include_machine: bool) -> AutostartListing:
    if root is None or not include_machine:
        return AutostartListing((), ())
    items: list[AutostartItem] = []
    skipped: list[AutostartSkipped] = []
    found: list[_Found] = []
    _walk(root, "", found, skipped)
    for task in sorted(found, key=lambda f: f.name.casefold()):
        try:
            item = _item(task)
        except BrokenEntryError as error:
            skipped.append(_skip(task.path, str(error)))
        else:
            if item is not None:
                items.append(item)
    return AutostartListing(tuple(items), tuple(skipped))


def _skip(path: Path, detail: str) -> AutostartSkipped:
    return AutostartSkipped(Source.SCHEDULED_TASK, str(path), detail)


def _walk(folder: Path, prefix: str, found: list[_Found], skipped: list[AutostartSkipped]) -> None:
    """Every file below ``folder``; linked folders are not followed (``read_entry`` skips them)."""
    try:
        children = list(folder.iterdir())
    except FileNotFoundError:
        return
    except OSError as error:
        skipped.append(_skip(folder, f"cannot read: {error.strerror}"))
        return
    for child in children:
        name = rf"{prefix}\{child.name}"
        if child.is_dir() and not child.is_symlink():
            _walk(child, name, found, skipped)
        else:
            found.append(_Found(name, child))


def _item(task: _Found) -> AutostartItem | None:
    raw = read_entry(task.path)
    root = _parse(raw)
    if root.tag != _NS + "Task":
        raise BrokenEntryError("not a task definition")
    triggers, any_enabled = _triggers(root)
    if not triggers:
        return None
    settings = root.find(_NS + "Settings")
    task_enabled = settings is None or _enabled(settings)
    command, notes = _first_action(root)
    return AutostartItem(
        source=Source.SCHEDULED_TASK,
        scope=Scope.SYSTEM,
        name=task.name,
        command=command,
        location=str(task.path),
        enabled=task_enabled and any_enabled,
        digest=entry_digest(raw),
        notes=(*triggers, *notes, *(() if task_enabled else ("task disabled",))),
    )


def _parse(raw: bytes) -> ET.Element:
    def refuse(*_: object) -> None:
        raise BrokenEntryError("a DTD is not allowed")

    guard = expat.ParserCreate()
    guard.StartDoctypeDeclHandler = refuse
    try:
        guard.Parse(raw, True)
        return ET.fromstring(raw)
    except (expat.ExpatError, ET.ParseError) as error:
        raise BrokenEntryError(f"not valid XML: {error}") from None


def _triggers(root: ET.Element) -> tuple[list[str], bool]:
    """The notes of the boot and logon triggers, and whether any of them is enabled."""
    notes: list[str] = []
    any_enabled = False
    for tag, note in _TRIGGERS:
        for trigger in root.iterfind(f"{_NS}Triggers/{_NS}{tag}"):
            user = trigger.findtext(_NS + "UserId")
            text = f"{note} of {user}" if user else note
            if _enabled(trigger):
                any_enabled = True
            else:
                text += " (trigger disabled)"
            notes.append(text)
    return notes, any_enabled


def _enabled(element: ET.Element) -> bool:
    text = element.findtext(_NS + "Enabled")
    if text is None:
        return True
    if text.strip() not in _BOOLEANS:
        raise BrokenEntryError("Enabled is not a boolean")
    return _BOOLEANS[text.strip()]


def _first_action(root: ET.Element) -> tuple[str, tuple[str, ...]]:
    actions = root.findall(f"{_NS}Actions/*")
    if not actions:
        raise BrokenEntryError("no actions")
    command, notes = _action(actions[0])
    more = len(actions) - 1
    if more:
        notes = (*notes, f"{more} more action{'s' if more > 1 else ''}")
    return command, notes


def _action(action: ET.Element) -> tuple[str, tuple[str, ...]]:
    kind = action.tag.removeprefix(_NS)
    if kind == "Exec":
        command = (action.findtext(_NS + "Command") or "").strip()
        if not command:
            raise BrokenEntryError("empty command")
        arguments = action.findtext(_NS + "Arguments")
        return (f"{command} {arguments}" if arguments else command), ()
    if kind == "ComHandler":
        class_id = (action.findtext(_NS + "ClassId") or "").strip()
        if not class_id:
            raise BrokenEntryError("COM handler without ClassId")
        return f"COM handler {class_id}", ("COM handler, not resolved",)
    raise BrokenEntryError(f"unsupported action {kind}")
