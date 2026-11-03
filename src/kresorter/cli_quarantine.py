"""``kresorter quarantine add | list | restore | purge`` (decisions 0004, 0006-0010).

Every command checks the data directory before creating anything, takes the single-instance
lock, opens the journal there and runs ``recover()`` first; an action that then finds work of
another domain refuses and names ``kresorter recover`` (item 127). ``purge`` shows its plan and
deletes only with ``--yes``, in the same process (decision 0008). ``add --from-analysis``
analyzes inside the lock, shows its plan and moves files only with ``--yes`` (decision 0010);
REVIEW findings and kept duplicate copies are never part of the plan.

Exit codes: 0 everything requested was done; 1 something was refused, not confirmed or there
was nothing to do; 2 usage error (argparse); 3 the quarantine cannot run safely here.
"""

from __future__ import annotations

import argparse
import functools
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from kresorter import cli_analyze
from kresorter.analysis.run import analyze_paths
from kresorter.analysis.score import Level
from kresorter.analysis.size_age import Thresholds
from kresorter.cli_journal import RECOVER, UNSAFE, unfinished, with_journal
from kresorter.core.models import FileEntry
from kresorter.core.preflight import Candidate, UnreliableCheckerError
from kresorter.core.scanner import ScanContext
from kresorter.quarantine.journal import quarantined
from kresorter.quarantine.recovery import RecoveryReport
from kresorter.quarantine.service import PurgeRefused, QuarantineService, RestoreRefused
from kresorter.storage.pending import pending_domains
from kresorter.text import count, format_size, refusal_line, refusals

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
    session = functools.partial(_run_locked, args, context, out, err)
    return with_journal(context, err, session, recover=RECOVER)


def _run_locked(
    args: argparse.Namespace,
    context: ScanContext,
    out: TextIO,
    err: TextIO,
    conn: sqlite3.Connection,
    data_dir: Path,
) -> int:
    try:
        service = _service(conn, context, err)
        if service is None:
            return UNSAFE
        report_recovery(service.recover(), out, err)
        others = set() if args.action == "list" else pending_domains(conn)
        if others:  # its own was recovered above (item 127)
            err.write(unfinished(others))
            return UNSAFE
        return _ACTIONS[args.action](Session(service, conn, context), args, out)
    except UnreliableCheckerError:
        err.write("kresorter: no reliable open-file check on this system; nothing was changed\n")
        return UNSAFE


def _service(
    conn: sqlite3.Connection, context: ScanContext, err: TextIO
) -> QuarantineService | None:
    """The service and its vault; ``None``, with the reason, if the vault cannot be used."""
    try:
        return QuarantineService(
            conn,
            policy=context.policy,
            open_files=context.open_files,
            classifier=context.classifier,
        )
    except OSError as error:  # the vault is created and made private here (item 112)
        err.write(f"kresorter: cannot use the vault: {error}\n")
        return None


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
    _, analysis = analyze_paths(args.paths, session.context, Thresholds())
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
    lines += refusals([refusal_line(r) for r in result.refused])
    _write(out, lines)
    return 1 if result.refused or result.error else 0


def _list(session: Session, args: argparse.Namespace, out: TextIO) -> int:
    items = quarantined(session.conn)
    total = sum(item.size for item in items)
    lines = [f"Quarantine: {count(len(items), 'file')}, {format_size(total)}"]
    lines += [f"  [{i.item_id}] {i.original}  {format_size(i.size)}" for i in items]
    _write(out, lines)
    return 0


def _restore(session: Session, args: argparse.Namespace, out: TextIO) -> int:
    result = session.service.restore(args.ids)
    lines = [f"Restored {count(len(result.restored), 'file')}:"]
    lines += [f"  [{r.item_id}] {r.original}" for r in result.restored]
    lines += refusals([_item_refusal(r) for r in result.refused])
    _write(out, lines)
    return 1 if result.refused else 0


def _purge(session: Session, args: argparse.Namespace, out: TextIO) -> int:
    plan = session.service.plan_purge(args.ids)
    if not plan.items:
        _write(out, ["Nothing to delete.", *refusals([_item_refusal(r) for r in plan.refused])])
        return 1
    planned = [f"  [{i.item_id}] {i.original}  {format_size(i.size)}" for i in plan.items]
    if not args.yes:
        files = f"{count(len(plan.items), 'file')}, {format_size(plan.total_bytes)}"
        lines = [f"Would permanently delete {files}:", *planned]
        lines.append("Nothing was deleted. Re-run with --yes to delete these files permanently.")
        _write(out, [*lines, *refusals([_item_refusal(r) for r in plan.refused])])
        return 1
    result = session.service.purge(plan)
    files = f"{count(len(result.purged), 'file')}, {format_size(result.freed_bytes)}"
    lines = [*planned, f"Permanently deleted {files}"]
    _write(out, [*lines, *refusals([_item_refusal(r) for r in result.refused])])
    return 1 if result.refused else 0


_ACTIONS: dict[str, Action] = {"add": _add, "list": _list, "restore": _restore, "purge": _purge}


# --- rendering ---------------------------------------------------------------------------------


def report_recovery(report: RecoveryReport, out: TextIO, err: TextIO) -> bool:
    """Show what the recovery found, warnings on ``err``; was there anything?"""
    found = report.quarantined + report.rolled_back + report.restored + report.purged
    found += report.lost
    if found:
        files = count(len(found), "file")
        out.write(f"Recovered an interrupted quarantine operation ({files}).\n")
    for warning in report.warnings:
        err.write(f"kresorter: {warning}\n")
    return bool(found)


def _item_refusal(refused: RestoreRefused | PurgeRefused) -> str:
    detail = f": {refused.detail}" if refused.detail else ""
    return f"  [{refused.item_id}] {refused.reason}{detail}"


def _write(out: TextIO, lines: Sequence[str]) -> None:
    out.write("\n".join(lines) + "\n")
