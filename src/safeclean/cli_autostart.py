"""``safeclean autostart list | disable | enable`` (decision 0011).

``list`` reports every autostart entry of this system: grouped by source in reader order; on
Windows, machine-wide entries are read only with ``--include-machine``, and the report says
when they were not. It creates, changes and deletes nothing and opens no journal.

``disable`` and ``enable`` open the shared journal (data directory, lock), reconcile the
interrupted autostart changes of this platform, then change one entry named by any unique
beginning of its digest, only with ``--yes`` (without it they show what would be written).
``autostart recover`` is ``safeclean recover`` (``cli_recover``, item 126).

Exit codes: 0 done; 1 refused, rolled back, not confirmed or no such entry; 2 usage error
(argparse); 3 failed, unfinished work of another domain, an unfinished change that cannot be
checked, or a data directory, lock or journal that cannot be used.
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from safeclean.autostart.changes import AutostartStore, XdgChanges
from safeclean.autostart.entries import BrokenEntryError
from safeclean.autostart.journal import ChangeRecovery, ChangeRefusal, ChangeResult, ChangeState
from safeclean.autostart.listing import AutostartContext, list_autostart
from safeclean.autostart.models import (
    AutostartItem,
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
)
from safeclean.autostart.registry import RegistryError
from safeclean.autostart.run_changes import RunKeyChanges
from safeclean.autostart.xdg import autostart_dirs
from safeclean.cli_journal import UNSAFE, unfinished, with_journal
from safeclean.core.scanner import ScanContext
from safeclean.storage.pending import pending_domains
from safeclean.text import count

MACHINE_NOTE = (
    "Note: machine-wide entries (HKLM, services, scheduled tasks, the common startup folder)"
    " were not read; add --include-machine to read them."
)

_ID = re.compile(r"[0-9a-fA-F]{1,32}")
ID_LENGTH = 12  # shown by list; any unique beginning is accepted
RECOVER = "safeclean autostart recover"
_UNREADABLE = (
    "safeclean: an unfinished autostart change cannot be checked: {}; fix or move what is"
    " there, then run 'safeclean autostart recover' again\n"
)
_UNCLOSED = (
    "safeclean: an unfinished autostart change cannot be closed: {}; fix or move what is"
    " there, then run 'safeclean autostart recover' again\n"
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
    actions.add_parser("recover", help="the same as 'safeclean recover'")
    for action in ("disable", "enable"):
        change = actions.add_parser(action, help=f"{action} one entry (reversible)")
        change.add_argument(
            "id", type=autostart_id, help="its id from 'autostart list' (any unique beginning)"
        )
        change.add_argument("--yes", action="store_true", help=f"confirm: {action} it")


def autostart_id(text: str) -> str:
    """The beginning of a digest, any case; anything else is a usage error."""
    if _ID.fullmatch(text) is None:
        raise argparse.ArgumentTypeError("not the beginning of an autostart id (1-32 hex digits)")
    return text.lower()


def run(
    args: argparse.Namespace,
    context: AutostartContext,
    scan: Callable[[], ScanContext],
    out: TextIO,
    err: TextIO,
) -> int:
    """``list``, ``disable`` or ``enable``; ``recover`` is ``cli_recover``'s."""
    if args.action == "list":
        return _list(args, context, out)
    session = functools.partial(_change, args, context, out, err)
    return with_journal(scan(), err, session, recover=RECOVER)


def _list(args: argparse.Namespace, context: AutostartContext, out: TextIO) -> int:
    listing = list_autostart(context, include_machine=args.include_machine)
    if args.json:
        out.write(render_json(listing, context, include_machine=args.include_machine))
    else:
        note = context.platform == "windows" and not args.include_machine
        out.write(render_text(listing, machine_note=note))
    return 0


def recovered(changes: XdgChanges | RunKeyChanges | None, err: TextIO) -> ChangeRecovery | None:
    """The autostart ``recover()``; ``None``, with the reason, if a change stays unfinished."""
    try:
        return ChangeRecovery() if changes is None else changes.recover()
    except (BrokenEntryError, RegistryError) as error:
        err.write(_UNREADABLE.format(error))
    except OSError as error:  # what it has to move cannot be moved (items 96, 113)
        err.write(_UNCLOSED.format(error))
    return None


def _change(
    args: argparse.Namespace,
    context: AutostartContext,
    out: TextIO,
    err: TextIO,
    conn: sqlite3.Connection,
    data_dir: Path,
) -> int:
    changes = changes_for(context, conn, data_dir)
    report = recovered(changes, err)
    if report is None:
        return UNSAFE
    out.write(render_recovery(report))
    matches = [
        item
        for item in list_autostart(context, include_machine=False).items
        if item.digest.startswith(args.id)
    ]
    if len(matches) != 1:
        out.write(_not_one(args.id, len(matches)))
        return 1
    (item,) = matches
    if changes is None or not item.disableable:
        out.write(f"Refused: {item.source} entries are read-only.\n")
        return 1
    if item.enabled is (args.action == "enable"):
        out.write(f"{item.name} is already {args.action}d; nothing to do.\n")
        return 1
    if not args.yes:
        out.write(_preview(args.action, item, context))
        return 1
    act = changes.disable if args.action == "disable" else changes.enable
    try:
        result = act(item)
    except (BrokenEntryError, RegistryError) as error:  # read back: left unfinished (item 90)
        err.write(_UNREADABLE.format(error))
        return UNSAFE
    except OSError as error:  # a check before acting: nothing is journaled (items 111, 113)
        err.write(f"safeclean: cannot {args.action} {item.name}: {error}; nothing was changed\n")
        return UNSAFE
    if result.refusal is ChangeRefusal.PENDING:  # another domain's: its own was recovered above
        err.write(unfinished(pending_domains(conn)))
        return UNSAFE
    return _outcome(result, item, args.action, out, err)


def _not_one(change_id: str, found: int) -> str:
    if found == 0:
        return (
            f"No autostart entry has id {change_id}; it may have changed since it was listed."
            " Run 'safeclean autostart list'.\n"
        )
    return f"Id {change_id} matches {found} entries; give more of it.\n"


def _preview(action: str, item: AutostartItem, context: AutostartContext) -> str:
    lines = [
        f"Would {action} {item.name} ({item.source}, {item.scope}):",
        f"  location: {item.location}",
        f"  {_how(action, item, context)}",
        f"Nothing was changed. Re-run with --yes to {action} it.",
    ]
    return "\n".join(lines) + "\n"


def _how(action: str, item: AutostartItem, context: AutostartContext) -> str:
    """What the change writes, in the user's words (decision 0011, item 8)."""
    if item.source is Source.RUN_KEY:
        state = "disabled, as the Task Manager does" if action == "disable" else "enabled"
        return f"its StartupApproved flag is set to {state}; the Run value is never written"
    if action == "enable":
        return (
            "if safeclean disabled it, what it changed is put back (the original from the"
            " store, or the stub moved to the store); nothing is deleted"
        )
    if item.scope is Scope.USER:
        return (
            "its file is replaced by a copy with Hidden=true; the original is kept in the"
            " autostart store"
        )
    user, _ = autostart_dirs(context.env, context.home)
    return f"a stub with Hidden=true is created in {user}; the system file is never written"


def _outcome(
    result: ChangeResult, item: AutostartItem, action: str, out: TextIO, err: TextIO
) -> int:
    if result.refusal is not None:
        out.write(f"Refused: {result.refusal}: {result.detail}\n")
        return 1
    if result.state is ChangeState.DONE:
        out.write(f"{action.capitalize()}d {item.name} (change {result.change_id}).\n")
        return 0
    if result.state is ChangeState.ROLLED_BACK:
        out.write(
            f"Not changed: {result.detail}; it was rolled back (change {result.change_id}).\n"
        )
        return 1
    err.write(
        f"safeclean: change {result.change_id} failed: {result.detail};"
        " run 'safeclean autostart recover'\n"
    )
    return UNSAFE


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
        return ""
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
    lines += [f"    note: {note}" for note in item.notes]
    return [*lines, f"    id: {item.digest[:ID_LENGTH]}"]


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
