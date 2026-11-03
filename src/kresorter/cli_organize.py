"""``kresorter organize move | list | undo`` (decision 0012, items 1-5, 7, 29-31 and 33-37).

``move`` and ``undo`` refuse first where organize does not move files (item 37): before the
journal is opened and before anything is planned. Every command then checks the data
directory, takes the single-instance lock, opens the journal there and recovers organize's own
batches; ``move`` and ``undo`` refuse while another domain's work is unfinished and name
``kresorter recover``, ``list`` runs. Without ``--yes`` the plan is shown and nothing is made,
moved or journaled; with it, the plan is made again inside the lock, checked once more
(preflight) and carried out as one batch, and the output says what moved, what was refused and
what stays. What recovery found is shown as ``kresorter recover`` shows it: each batch it
closed with its state, the files still sorted and the command that moves them back; an undo
batch that stopped names the batch it undoes, whose undo takes what is left. ``move`` without
``--yes`` takes ``--explain``: the files that stay are explained after the plan, once the lock
is released (``cli_llm``, decision 0013); with ``--yes`` it is a usage error.

Exit codes: 0 every planned move happened; 1 a preview, nothing to move, a refused folder or
batch, or a file refused at move time (files that stay by the plan are not refusals); 2 usage
error (argparse); 3 a system where organize does not move files, unfinished work of another
domain, a data directory, lock or journal that cannot be used, or a batch that stopped.
"""

from __future__ import annotations

import argparse
import functools
import os
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from kresorter import cli_llm
from kresorter.cli_journal import RECOVER, UNSAFE, unfinished, with_journal
from kresorter.core.heuristics import Platform
from kresorter.core.preflight import Refused
from kresorter.core.scanner import ScanContext
from kresorter.organize.folders import FolderRefused
from kresorter.organize.journal import BatchKind, BatchState, summaries
from kresorter.organize.mover import BatchResult, Planned, carry_out, check
from kresorter.organize.planner import Move, Stay, plan
from kresorter.organize.platforms import refusal, renamer
from kresorter.organize.recovery import RecoveredBatch, RecoveryReport, recover
from kresorter.organize.undo import UndoMove, UndoRefused, plan_undo
from kresorter.storage.pending import pending_domains
from kresorter.text import count, format_size, refusal_line, refusals

UNDO = "kresorter organize undo"

Action = Callable[[sqlite3.Connection, argparse.Namespace, ScanContext, TextIO, list[Stay]], int]
Done = Callable[[int], tuple[list[str], list[str]]]  # batch id -> lines before and after


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    organize = commands.add_parser("organize", help="sort a folder's files by kind (reversible)")
    actions = organize.add_subparsers(dest="action", required=True)
    move = actions.add_parser("move", help="sort the files directly in a folder by kind")
    move.add_argument("folder", help="the folder to sort")
    yes_or_explain = move.add_mutually_exclusive_group()  # what acts is never explained
    yes_or_explain.add_argument("--yes", action="store_true", help="confirm: move the files")
    cli_llm.add_explain(yes_or_explain)
    actions.add_parser("list", help="show organize's batches")
    undo = actions.add_parser("undo", help="move back what a batch moved")
    undo.add_argument("batch", type=int, help="a batch id from 'list'")
    undo.add_argument("--yes", action="store_true", help="confirm: move the files back")


def run(
    args: argparse.Namespace,
    context: ScanContext,
    out: TextIO,
    err: TextIO,
    explainer: cli_llm.Explainer | None = None,
) -> int:
    if args.action != "list":
        blocked = refusal(context.platform, context.open_files)
        if blocked is not None:
            err.write(blocked)
            return UNSAFE
    stays: list[Stay] = []  # what the plan shown leaves in place, for --explain
    session = functools.partial(_run_locked, args, context, out, err, stays)
    code = with_journal(context, err, session, recover=RECOVER)
    explained = cli_llm.ask(explainer, stays)  # after the lock: the plan is final
    out.write(cli_llm.section(explained))
    cli_llm.notify(explained, err)
    return code


def _run_locked(
    args: argparse.Namespace,
    context: ScanContext,
    out: TextIO,
    err: TextIO,
    stays: list[Stay],
    conn: sqlite3.Connection,
    data_dir: Path,
) -> int:
    report_recovery(recover(conn), out, err)
    others = set() if args.action == "list" else pending_domains(conn)
    if others:  # its own was recovered above (0011 item 127)
        err.write(unfinished(others))
        return UNSAFE
    return _ACTIONS[args.action](conn, args, context, out, stays)


# --- actions -----------------------------------------------------------------------------------


def _move(
    conn: sqlite3.Connection,
    args: argparse.Namespace,
    ctx: ScanContext,
    out: TextIO,
    shown: list[Stay],
) -> int:
    folder = Path(os.path.normpath(Path(args.folder).absolute()))  # links are not resolved
    try:
        found = plan(folder, ctx)
    except FolderRefused as no:
        detail = f" ({no.detail})" if no.detail else ""
        _write(out, [f"Refused: {folder}: {no.reason}{detail}"])
        return 1
    folder = found.folder  # on Windows, as the system spells it (decision 0017, item 12)
    shown.extend(found.stays)
    stays = _stays(found.stays, folder)
    if not found.moves:
        _write(out, [f"Nothing to move in {folder}.", *stays])
        return 1
    if not args.yes:
        lines = [f"Would move {_files(found.moves)}, in {folder}:", *_by_category(found.moves)]
        lines += [*stays, "Nothing was moved. Re-run with --yes to move these files."]
        _write(out, lines)
        return 1
    cleared, refused = check(found.moves, folder, ctx)
    if not cleared:
        _write(out, [f"Nothing was moved in {folder}.", *_refused(refused), *stays])
        return 1

    def done(batch_id: int) -> tuple[list[str], list[str]]:
        them = "it" if len(cleared) == 1 else "them"
        head = [f"Moved {_files(cleared)}, in {folder} (batch {batch_id}):"]
        return [*head, *_by_category(cleared)], [f"'{UNDO} {batch_id}' moves {them} back"]

    return _carry(conn, folder, cleared, refused, stays, out, platform=ctx.platform, done=done)


def _undo(
    conn: sqlite3.Connection,
    args: argparse.Namespace,
    ctx: ScanContext,
    out: TextIO,
    shown: list[Stay],
) -> int:
    try:
        found = plan_undo(conn, args.batch)
    except UndoRefused as no:
        _write(out, [f"Refused: batch {no.batch_id}: {no.reason}"])
        return 1
    folder = found.folder
    stays = _stays(found.stays, folder)
    if not found.moves:
        _write(out, [f"Nothing to move back from batch {args.batch}.", *stays])
        return 1
    if not args.yes:
        files = _files(found.moves)
        lines = [f"Would move back {files}, sorted by batch {args.batch} in {folder}:"]
        lines += [*_back(found.moves, folder), *stays]
        _write(out, [*lines, "Nothing was moved. Re-run with --yes to move these files back."])
        return 1
    cleared, refused = check(found.moves, folder, ctx)
    if not cleared:
        nothing = f"Nothing was moved back from batch {args.batch}."
        _write(out, [nothing, *_refused(refused), *stays])
        return 1

    def done(batch_id: int) -> tuple[list[str], list[str]]:
        head = f"Moved back {_files(cleared)}, in {folder} (batch {batch_id}, undoing batch"
        return [f"{head} {args.batch}):", *_back(cleared, folder)], []

    undoes = [move.undoes for move in cleared]
    return _carry(
        conn,
        folder,
        cleared,
        refused,
        stays,
        out,
        platform=ctx.platform,
        done=done,
        undoes=undoes,
        undoing=args.batch,
    )


def _list(
    conn: sqlite3.Connection,
    args: argparse.Namespace,
    ctx: ScanContext,
    out: TextIO,
    shown: list[Stay],
) -> int:
    found = summaries(conn)
    if not found:
        _write(out, ["No organize batches."])
        return 0
    lines = [f"Organize batches: {len(found)}"]
    for summary in found:
        batch = summary.batch
        kind = "organize" if batch.kind is BatchKind.ORGANIZE else f"undo of batch {batch.undoing}"
        state = str(batch.state)
        if summary.undone:
            state += ", undone" if summary.undone == summary.moved else ", partly undone"
        seconds = batch.created_at_ns // 1_000_000_000
        when = datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        moved = f"{count(summary.moved, 'file')} moved"
        lines.append(f"  [{batch.batch_id}] {when}  {kind}  {moved}  {state}  {batch.folder}")
    _write(out, lines)
    return 0


_ACTIONS: dict[str, Action] = {"move": _move, "list": _list, "undo": _undo}


def _carry(
    conn: sqlite3.Connection,
    folder: Path,
    cleared: Sequence[Planned],
    refused: Sequence[Refused],
    stays: list[str],
    out: TextIO,
    *,
    platform: Platform,
    done: Done,
    undoes: Sequence[int] | None = None,
    undoing: int | None = None,
) -> int:
    """Carry the cleared moves out as one batch, renamed as ``platform`` renames (decision
    0017, item 3), an undo of ``undoing`` when ``undoes`` names the move each one reverses, and
    say what happened."""
    moves = [(move.source, move.destination) for move in cleared]
    result = carry_out(conn, folder, moves, rename=renamer(platform), undoes=undoes)
    if result.state is not BatchState.DONE:
        _write(out, [*_stopped(result, undoing), *_refused(refused), *stays])
        return UNSAFE
    head, tail = done(result.batch_id)
    _write(out, [*head, *_refused(refused), *stays, *tail])
    return 1 if refused else 0


# --- rendering ---------------------------------------------------------------------------------


def report_recovery(report: RecoveryReport, out: TextIO, err: TextIO) -> bool:
    """Show what the recovery found, warnings on ``err``; was there anything?"""
    if report.batches:
        batches = len(report.batches)
        noun = "batch" if batches == 1 else "batches"
        lines = [f"Recovered {batches} interrupted organize {noun}:"]
        for batch in report.batches:
            lines += _batch_lines(batch)
        _write(out, lines)
    for warning in report.warnings:
        err.write(f"kresorter: {warning}\n")
    return bool(report.batches)


def _batch_lines(batch: RecoveredBatch) -> list[str]:
    """A batch that was interrupted or stopped: its state, and what is left to undo."""
    line = f"  [{batch.batch_id}] {batch.state}"
    if batch.kind is BatchKind.UNDO:
        if batch.state is not BatchState.DONE:
            line += f": the undo of batch {batch.undoing} stopped;"
            line += f" '{UNDO} {batch.undoing}' moves back the files still sorted"
        return [line]
    if batch.left:
        them = "it" if len(batch.left) == 1 else "them"
        line += f": {count(len(batch.left), 'file')} still sorted;"
        line += f" '{UNDO} {batch.batch_id}' moves {them} back"
    return [line, *(f"    {path}" for path in batch.left)]


def _stopped(result: BatchResult, undoing: int | None) -> list[str]:
    kind = BatchKind.ORGANIZE if undoing is None else BatchKind.UNDO
    stopped = RecoveredBatch(result.batch_id, result.state, result.left, kind, undoing)
    return [f"Stopped: {result.error}", *_batch_lines(stopped)]


def _files(moves: Sequence[Planned]) -> str:
    return f"{count(len(moves), 'file')}, {format_size(sum(move.size for move in moves))}"


def _by_category(moves: Sequence[Move]) -> list[str]:
    groups: dict[str, list[Move]] = {}
    for move in moves:
        groups.setdefault(move.category, []).append(move)
    lines: list[str] = []
    for category, group in groups.items():
        lines.append(f"  {category}: {_files(group)}")
        lines += [f"    {move.source.name} -> {category}/" for move in group]
    return lines


def _back(moves: Sequence[UndoMove], folder: Path) -> list[str]:
    return [
        f"  {os.path.relpath(move.source, folder)} -> {os.path.relpath(move.destination, folder)}"
        for move in moves
    ]


def _stays(stays: Sequence[Stay], folder: Path) -> list[str]:
    if not stays:
        return []
    lines = [f"Stays {len(stays)}:"]
    for stay in stays:
        detail = f" ({stay.detail})" if stay.detail else ""
        lines.append(f"  {stay.reason}: {os.path.relpath(stay.path, folder)}{detail}")
    return lines


def _refused(refused: Sequence[Refused]) -> list[str]:
    return refusals([refusal_line(r) for r in refused])


def _write(out: TextIO, lines: Sequence[str]) -> None:
    out.write("\n".join(lines) + "\n")
