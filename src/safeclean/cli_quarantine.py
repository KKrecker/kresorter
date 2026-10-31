"""``safeclean quarantine add | list | restore | purge`` (decisions 0004, 0006-0010).

Every command checks the data directory before creating anything, takes the single-instance
lock, opens the journal there and runs ``recover()`` first. ``purge`` shows its plan and
deletes only with ``--yes``, in the same process (decision 0008). ``add --from-analysis``
analyzes inside the lock, shows its plan and moves files only with ``--yes`` (decision 0010);
REVIEW findings and kept duplicate copies are never part of the plan.

Exit codes: 0 everything requested was done; 1 something was refused, not confirmed or there
was nothing to do; 2 usage error (argparse); 3 the quarantine cannot run safely here.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from safeclean import cli_analyze
from safeclean.analysis.score import Level
from safeclean.analysis.size_age import Thresholds
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
from safeclean.storage.lock import InstanceLock, LockedError
from safeclean.text import count, format_size

JOURNAL_NAME = "journal.db"
LOCK_NAME = "safeclean.lock"
UNSAFE = 3

# Levels a bulk add may take, each including the stricter ones before it; REVIEW never.
BULK_LEVELS = {"safe": (Level.SAFE,), "likely_safe": (Level.SAFE, Level.LIKELY_SAFE)}


@dataclass(frozen=True)
class Session:
    service: QuarantineService
    conn: sqlite3.Connection
    context: ScanContext


Action = Callable[[Session, argparse.Namespace, TextIO], int]


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    quarantine = commands.add_parser("quarantine", help="move files aside, restore or purge them")
    actions = quarantine.add_subparsers(dest="action", required=True)
    add = actions.add_parser("add", help="move files into the quarantine (reversible)")
    add.add_argument(
        "paths",
        nargs="*",
        help="files to quarantine; with --from-analysis, directories to analyze "
        "(default: safe zones)",
    )
    add.add_argument(
        "--from-analysis", action="store_true", help="quarantine what 'analyze' proposes"
    )
    add.add_argument(
        "--level", choices=list(BULK_LEVELS), help="with --from-analysis: the least safe level"
    )
    add.add_argument("--yes", action="store_true", help="with --from-analysis: confirm the move")
    actions.add_parser("list", help="show quarantined files")
    restore = actions.add_parser("restore", help="put quarantined files back")
    restore.add_argument("ids", nargs="+", type=int, help="item ids from 'list'")
    purge = actions.add_parser("purge", help="permanently delete quarantined files")
    purge.add_argument("ids", nargs="+", type=int, help="item ids from 'list'")
    purge.add_argument("--yes", action="store_true", help="confirm: delete permanently")


def check_usage(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Combinations argparse cannot express; exits with 2 like any usage error."""
    if args.command != "quarantine" or args.action != "add":
        return
    if args.from_analysis:
        if args.level is None:
            parser.error("quarantine add: --from-analysis needs --level")
    elif args.level is not None or args.yes:
        parser.error("quarantine add: --level and --yes only go with --from-analysis")
    elif not args.paths:
        parser.error("quarantine add: name the files to quarantine, or use --from-analysis")


def run(args: argparse.Namespace, context: ScanContext, out: TextIO, err: TextIO) -> int:
    try:
        data_dir = check_data_dir(context.policy, context.classifier)
    except QuarantineError as error:
        err.write(f"safeclean: {error}\n")
        return UNSAFE
    try:
        data_dir.mkdir(mode=PRIVATE, parents=True, exist_ok=True)
        with InstanceLock(data_dir / LOCK_NAME):
            return _run_locked(args, context, data_dir, out, err)
    except LockedError as error:
        err.write(f"safeclean: {error}\n")
        return UNSAFE
    except OSError as error:
        err.write(f"safeclean: cannot use the data directory: {error}\n")
        return UNSAFE


def _run_locked(
    args: argparse.Namespace, context: ScanContext, data_dir: Path, out: TextIO, err: TextIO
) -> int:
    try:
        conn = connect(data_dir / JOURNAL_NAME)
    except (OSError, sqlite3.Error, StorageError) as error:
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
        return _ACTIONS[args.action](Session(service, conn, context), args, out)
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


def _add(session: Session, args: argparse.Namespace, out: TextIO) -> int:
    if args.from_analysis:
        return _add_from_analysis(session, args, out)
    candidates = [Candidate(entry=entry_for(Path(p))) for p in args.paths]
    return _quarantine(session.service, candidates, out)


def _add_from_analysis(session: Session, args: argparse.Namespace, out: TextIO) -> int:
    _, analysis = cli_analyze.analyze_paths(args.paths, session.context, Thresholds())
    levels = BULK_LEVELS[args.level]
    chosen = [f for f in analysis.proposed if f.level in levels]
    if not chosen:
        _write(out, ["Nothing to quarantine."])
        return 1
    if not args.yes:
        files = f"{count(len(chosen), 'file')}, {format_size(sum(f.entry.size for f in chosen))}"
        lines = [f"Would quarantine {files} (level: {args.level}):"]
        for finding in chosen:
            lines += cli_analyze.finding_lines(finding)
        lines.append("Nothing was moved. Re-run with --yes to quarantine these files.")
        _write(out, lines)
        return 1
    return _quarantine(session.service, [f.candidate for f in chosen], out)


def _quarantine(service: QuarantineService, candidates: list[Candidate], out: TextIO) -> int:
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


def _list(session: Session, args: argparse.Namespace, out: TextIO) -> int:
    rows = session.conn.execute(
        "SELECT id, original_path, size FROM items WHERE state = ? ORDER BY id",
        (ItemState.QUARANTINED,),
    ).fetchall()
    total = sum(size for _, _, size in rows)
    lines = [f"Quarantine: {count(len(rows), 'file')}, {format_size(total)}"]
    lines += [f"  [{item_id}] {original}  {format_size(size)}" for item_id, original, size in rows]
    _write(out, lines)
    return 0


def _restore(session: Session, args: argparse.Namespace, out: TextIO) -> int:
    result = session.service.restore(args.ids)
    lines = [f"Restored {count(len(result.restored), 'file')}:"]
    lines += [f"  [{r.item_id}] {r.original}" for r in result.restored]
    lines += _refusals([_item_refusal(r) for r in result.refused])
    _write(out, lines)
    return 1 if result.refused else 0


def _purge(session: Session, args: argparse.Namespace, out: TextIO) -> int:
    plan = session.service.plan_purge(args.ids)
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
    result = session.service.purge(plan)
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
