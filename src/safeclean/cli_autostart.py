"""``safeclean autostart list | recover`` (decision 0011).

``list`` reports every autostart entry of this system: grouped by source in reader order; on
Windows, machine-wide entries are read only with ``--include-machine``, and the report says
when they were not. It creates, changes and deletes nothing and opens no journal.

``recover`` opens the shared journal (data directory, lock) and reconciles the interrupted
autostart changes of this platform. Exit codes: 0 done; 3 an unfinished change cannot be
checked, or the data directory, the lock or the journal cannot be used.
"""

from __future__ import annotations

import argparse
import functools
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from safeclean.autostart.changes import AutostartStore, ChangeRecovery, XdgChanges
from safeclean.autostart.entries import BrokenEntryError
from safeclean.autostart.listing import AutostartContext, list_autostart
from safeclean.autostart.models import AutostartItem, AutostartListing, AutostartSkipped, Source
from safeclean.autostart.registry import RegistryError
from safeclean.autostart.run_changes import RunKeyChanges
from safeclean.autostart.xdg import autostart_dirs
from safeclean.cli_journal import UNSAFE, with_journal
from safeclean.core.scanner import ScanContext
from safeclean.text import count

MACHINE_NOTE = (
    "Note: machine-wide entries (HKLM, services, scheduled tasks, the common startup folder)"
    " were not read; add --include-machine to read them."
)

_TITLES = {
    Source.XDG_AUTOSTART: "XDG autostart",
    Source.SYSTEMD_USER: "systemd user units",
    Source.RUN_KEY: "Run keys",
    Source.RUN_ONCE_KEY: "RunOnce keys",
    Source.STARTUP_FOLDER: "Startup folders",
    Source.SERVICE: "Services",
    Source.SCHEDULED_TASK: "Scheduled tasks",
    Source.LAUNCH_AGENT: "launchd",
}


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    autostart = commands.add_parser("autostart", help="programs that start on their own")
    actions = autostart.add_subparsers(dest="action", required=True)
    list_cmd = actions.add_parser("list", help="list autostart entries; report only")
    list_cmd.add_argument("--json", action="store_true", help="machine-readable output")
    list_cmd.add_argument(
        "--include-machine",
        action="store_true",
        help="Windows: also read HKLM, services, scheduled tasks and the common startup folder",
    )
    actions.add_parser("recover", help="reconcile interrupted autostart changes with the system")


def run(
    args: argparse.Namespace,
    context: AutostartContext,
    scan: Callable[[], ScanContext],
    out: TextIO,
    err: TextIO,
) -> int:
    if args.action == "list":
        return _list(args, context, out)
    return with_journal(scan(), err, functools.partial(_recover, context, out, err))


def _list(args: argparse.Namespace, context: AutostartContext, out: TextIO) -> int:
    listing = list_autostart(context, include_machine=args.include_machine)
    if args.json:
        out.write(render_json(listing, context, include_machine=args.include_machine))
    else:
        note = context.platform == "windows" and not args.include_machine
        out.write(render_text(listing, machine_note=note))
    return 0


def _recover(
    context: AutostartContext, out: TextIO, err: TextIO, conn: sqlite3.Connection, data_dir: Path
) -> int:
    changes = changes_for(context, conn, data_dir)
    try:
        report = ChangeRecovery() if changes is None else changes.recover()
    except (BrokenEntryError, RegistryError) as error:
        err.write(
            f"safeclean: an unfinished autostart change cannot be checked: {error}; fix or move"
            " what is there, then run 'safeclean autostart recover' again\n"
        )
        return UNSAFE
    out.write(render_recovery(report))
    return 0


def changes_for(
    context: AutostartContext, conn: sqlite3.Connection, data_dir: Path
) -> XdgChanges | RunKeyChanges | None:
    """What can change autostart entries here: XDG on Linux, HKCU Run on Windows, else none."""
    if context.platform == "linux":
        user, system = autostart_dirs(context.env, context.home)
        return XdgChanges(conn, AutostartStore(data_dir), user, system)
    if context.platform == "windows":
        return RunKeyChanges(conn, context.registry())
    return None


def render_recovery(report: ChangeRecovery) -> str:
    closed = [(i, "done") for i in report.done]
    closed += [(i, "rolled_back") for i in report.rolled_back]
    closed += [(i, "failed") for i in report.failed]
    if not closed:
        return "Nothing to recover.\n"
    lines = [f"Recovered {count(len(closed), 'interrupted autostart change')}:"]
    lines += [f"  [{change_id}] {state}" for change_id, state in sorted(closed)]
    return "\n".join(lines) + "\n"


def render_text(listing: AutostartListing, *, machine_note: bool) -> str:
    disabled = sum(not item.enabled for item in listing.items)
    lines = [
        "safeclean autostart list - report only, nothing was changed",
        f"Entries: {len(listing.items)}, {disabled} disabled",
    ]
    if machine_note:
        lines.append(MACHINE_NOTE)
    by_source: dict[Source, list[AutostartItem]] = {}
    for item in listing.items:
        by_source.setdefault(item.source, []).append(item)
    for source, items in by_source.items():
        lines += ["", f"{_TITLES[source]}: {len(items)}"]
        lines += [line for item in items for line in _item_lines(item)]
    lines += ["", f"Skipped: {len(listing.skipped)}"]
    lines += [f"  {s.source}: {s.location} ({s.detail})" for s in listing.skipped]
    return "\n".join(lines) + "\n"


def _item_lines(item: AutostartItem) -> list[str]:
    marks = ["enabled" if item.enabled else "disabled", str(item.scope)]
    if item.disableable:
        marks.append("disableable")
    lines = [
        f"  {item.name}  [{', '.join(marks)}]",
        f"    command: {item.command}",
        f"    location: {item.location}",
    ]
    if item.shadows is not None:
        lines.append(f"    shadows: {item.shadows}")
    return lines + [f"    note: {note}" for note in item.notes]


def render_json(
    listing: AutostartListing, context: AutostartContext, *, include_machine: bool
) -> str:
    data: dict[str, Any] = {
        "platform": context.platform,
        "include_machine": include_machine,
        "items": [_item_json(item) for item in listing.items],
        "skipped": [_skip_json(skip) for skip in listing.skipped],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _item_json(item: AutostartItem) -> dict[str, Any]:
    return {
        "source": str(item.source),
        "scope": str(item.scope),
        "name": item.name,
        "command": item.command,
        "location": item.location,
        "enabled": item.enabled,
        "disableable": item.disableable,
        "digest": item.digest,
        "shadows": item.shadows,
        "notes": list(item.notes),
    }


def _skip_json(skip: AutostartSkipped) -> dict[str, Any]:
    return {"source": str(skip.source), "location": skip.location, "detail": skip.detail}
