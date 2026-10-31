"""``safeclean quarantine add | list | restore | purge`` (decisions 0004, 0006-0009).

Every command checks the data directory before creating anything, opens the journal there and
runs ``recover()`` first. ``purge`` shows its plan and deletes only with ``--yes``, in the same
process (decision 0008).

Exit codes: 0 everything requested was done; 1 something was refused, not confirmed or there
was nothing to do; 2 usage error (argparse); 3 the quarantine cannot run safely here.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from safeclean.core.models import FileEntry
from safeclean.core.scanner import ScanContext
from safeclean.quarantine.preflight import Candidate, RefusalReason, Refused, UnreliableCheckerError
from safeclean.quarantine.service import (
    ItemState,
    PurgeRefused,
    QuarantineError,
    QuarantineService,
    RecoveryReport,
    RestoreRefused,
    check_data_dir,
)
from safeclean.quarantine.vault import PRIVATE
from safeclean.storage.db import StorageError, connect
from safeclean.text import count, format_size

JOURNAL_NAME = "journal.db"
UNSAFE = 3

Action = Callable[[QuarantineService, sqlite3.Connection, argparse.Namespace, TextIO], int]


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    quarantine = commands.add_parser("quarantine", help="move files aside, restore or purge them")
    actions = quarantine.add_subparsers(dest="action", required=True)
    add = actions.add_parser("add", help="move files into the quarantine (reversible)")
    add.add_argument("paths", nargs="+", help="files to quarantine")
    actions.add_parser("list", help="show quarantined files")
    restore = actions.add_parser("restore", help="put quarantined files back")
    restore.add_argument("ids", nargs="+", type=int, help="item ids from 'list'")
    purge = actions.add_parser("purge", help="permanently delete quarantined files")
    purge.add_argument("ids", nargs="+", type=int, help="item ids from 'list'")
    purge.add_argument("--yes", action="store_true", help="confirm: delete permanently")


def run(args: argparse.Namespace, context: ScanContext, out: TextIO, err: TextIO) -> int:
    try:
        data_dir = check_data_dir(context.policy, context.classifier)
    except QuarantineError as error:
        err.write(f"safeclean: {error}\n")
        return UNSAFE
    try:
        data_dir.mkdir(mode=PRIVATE, parents=True, exist_ok=True)
        conn = connect(data_dir / JOURNAL_NAME)
    except (OSError, StorageError) as error:
        err.write(f"safeclean: cannot open the journal: {error}\n")
        return UNSAFE
    try:
        service = QuarantineService(
            conn,
            policy=context.policy,
            open_files=context.open_files,
            classifier=context.classifier,
        )
        _report_recovery(service.recover(), out, err)
        return _ACTIONS[args.action](service, conn, args, out)
    except UnreliableCheckerError:
        err.write("safeclean: no reliable open-file check on this system; nothing was changed\n")
        return UNSAFE
    finally:
        conn.close()


def entry_for(path: Path) -> FileEntry:
    """The named file as it is now. A missing one gets zeros; preflight refuses it."""
    absolute = path.absolute()
    try:
        info = absolute.lstat()
    except OSError:
        return FileEntry(path=absolute, size=0, mtime_ns=0)
    return FileEntry(path=absolute, size=info.st_size, mtime_ns=info.st_mtime_ns)


# --- actions -----------------------------------------------------------------------------------


def _add(
    service: QuarantineService, conn: sqlite3.Connection, args: argparse.Namespace, out: TextIO
) -> int:
    candidates = [Candidate(entry=entry_for(Path(p))) for p in args.paths]
    result = service.quarantine(candidates)
    sizes = {c.entry.path: c.entry.size for c in candidates}
    total = sum(sizes[m.original] for m in result.moved)
    lines = [f"Quarantined {count(len(result.moved), 'file')}, {format_size(total)}"]
    lines += [f"  [{m.item_id}] {m.original}" for m in result.moved]
    if result.error:
        lines.append(f"Stopped: {result.error}; files that had moved were put back")
    lines += _refusals([_path_refusal(r) for r in result.refused])
    _write(out, lines)
    return 1 if result.refused or result.error else 0


def _list(
    service: QuarantineService, conn: sqlite3.Connection, args: argparse.Namespace, out: TextIO
) -> int:
    rows = conn.execute(
        "SELECT id, original_path, size FROM items WHERE state = ? ORDER BY id",
        (ItemState.QUARANTINED,),
    ).fetchall()
    total = sum(size for _, _, size in rows)
    lines = [f"Quarantine: {count(len(rows), 'file')}, {format_size(total)}"]
    lines += [f"  [{item_id}] {original}  {format_size(size)}" for item_id, original, size in rows]
    _write(out, lines)
    return 0


def _restore(
    service: QuarantineService, conn: sqlite3.Connection, args: argparse.Namespace, out: TextIO
) -> int:
    result = service.restore(args.ids)
    lines = [f"Restored {count(len(result.restored), 'file')}:"]
    lines += [f"  [{r.item_id}] {r.original}" for r in result.restored]
    lines += _refusals([_item_refusal(r) for r in result.refused])
    _write(out, lines)
    return 1 if result.refused else 0


def _purge(
    service: QuarantineService, conn: sqlite3.Connection, args: argparse.Namespace, out: TextIO
) -> int:
    plan = service.plan_purge(args.ids)
    if not plan.items:
        _write(out, ["Nothing to delete.", *_refusals([_item_refusal(r) for r in plan.refused])])
        return 1
    planned = [f"  [{i.item_id}] {i.original}  {format_size(i.size)}" for i in plan.items]
    if not args.yes:
        files = f"{count(len(plan.items), 'file')}, {format_size(plan.total_bytes)}"
        lines = [f"Would permanently delete {files}:", *planned]
        lines.append("Nothing was deleted. Re-run with --yes to delete these files permanently.")
        _write(out, [*lines, *_refusals([_item_refusal(r) for r in plan.refused])])
        return 1
    result = service.purge(plan)
    files = f"{count(len(result.purged), 'file')}, {format_size(result.freed_bytes)}"
    lines = [*planned, f"Permanently deleted {files}"]
    _write(out, [*lines, *_refusals([_item_refusal(r) for r in result.refused])])
    return 1 if result.refused else 0


_ACTIONS: dict[str, Action] = {"add": _add, "list": _list, "restore": _restore, "purge": _purge}


# --- rendering ---------------------------------------------------------------------------------


def _report_recovery(report: RecoveryReport, out: TextIO, err: TextIO) -> None:
    found = report.quarantined + report.rolled_back + report.restored + report.purged
    found += report.lost
    if found:
        out.write(f"Recovered an interrupted operation ({count(len(found), 'file')}).\n")
    for warning in report.warnings:
        err.write(f"safeclean: {warning}\n")


def _path_refusal(refused: Refused) -> str:
    # Only a blacklist refusal says *which* rule blocked the path; for OPEN_FILE the policy
    # verdict repeats the reason and adds nothing.
    label = str(refused.reason)
    if refused.reason is RefusalReason.BLOCKED:
        label += f" ({refused.block_reason})"
    detail = f" ({refused.detail})" if refused.detail else ""
    return f"  {label}: {refused.path}{detail}"


def _item_refusal(refused: RestoreRefused | PurgeRefused) -> str:
    detail = f": {refused.detail}" if refused.detail else ""
    return f"  [{refused.item_id}] {refused.reason}{detail}"


def _refusals(lines: Sequence[str]) -> list[str]:
    return [f"Refused {len(lines)}:", *lines] if lines else []


def _write(out: TextIO, lines: Sequence[str]) -> None:
    out.write("\n".join(lines) + "\n")
