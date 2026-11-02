"""The window's sessions in the journal, run in a task's worker (decision 0014, items 11, 14, 21
and 23).

A session runs as the CLI's does: the data directory is checked, the lock taken and the journal
opened (``storage.session``); the domain's own unfinished work is recovered first, and
unfinished work of another domain refuses an action before anything is changed (a listing goes
on, as ``quarantine list`` and ``organize list``). A quarantine session needs a reliable
open-file check. Each one ends with the domain's state then: the quarantined files, organize's
batches. Organize's acts make their plan again inside the session and carry out only the
confirmed moves it still holds unchanged (item 14). What could not run is a value the page shows
in its words (``problem``). No Qt is needed here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from safeclean.core.preflight import Refused, UnreliableCheckerError
from safeclean.core.scanner import ScanContext
from safeclean.organize import recovery as organize_recovery
from safeclean.organize.folders import FolderRefused
from safeclean.organize.journal import Summary, summaries
from safeclean.organize.mover import BatchResult, Planned, carry_out, check
from safeclean.organize.planner import Move, Plan, plan
from safeclean.organize.undo import UndoMove, UndoPlan, UndoRefused, plan_undo
from safeclean.quarantine.journal import QuarantinedItem, quarantined
from safeclean.quarantine.recovery import RecoveryReport
from safeclean.quarantine.service import QuarantineService
from safeclean.storage.pending import Domain, pending_domains
from safeclean.storage.session import Journal, SessionFailed, run_session
from safeclean.ui.i18n import Translator

__all__ = [
    "Act",
    "Carried",
    "Done",
    "NoReliableCheck",
    "Organized",
    "Unfinished",
    "in_organize",
    "in_quarantine",
    "no_act",
    "plan_folder",
    "problem",
    "sort_folder",
    "undo_batch",
    "undo_plan",
]

T = TypeVar("T")
M = TypeVar("M", Move, UndoMove)
Act = Callable[[ScanContext, Journal], T]  # what an organize session does, inside it


@dataclass(frozen=True)
class Unfinished:
    """Other domains have unfinished work: Recover comes first."""

    domains: frozenset[Domain]


@dataclass(frozen=True)
class NoReliableCheck:
    """No reliable open-file check on this system."""


@dataclass(frozen=True)
class Done(Generic[T]):
    recovered: RecoveryReport  # the quarantine's own unfinished work, settled first
    result: T
    listed: tuple[QuarantinedItem, ...]  # the quarantine after ``result``


def in_quarantine(
    context: ScanContext, act: Callable[[QuarantineService], T], *, listing: bool = False
) -> Done[T] | Unfinished | NoReliableCheck | SessionFailed:
    """``act`` on the quarantine, inside the session, or why it did not run; a ``listing`` is
    not stopped by other domains' unfinished work."""

    def body(conn: Journal, data_dir: Path) -> Done[T] | Unfinished | NoReliableCheck:
        try:
            service = QuarantineService(
                conn,
                policy=context.policy,
                open_files=context.open_files,
                classifier=context.classifier,
            )
        except UnreliableCheckerError:
            return NoReliableCheck()
        recovered = service.recover()
        others = set() if listing else pending_domains(conn)
        if others:  # its own was recovered above (0011 item 127)
            return Unfinished(frozenset(others))
        result = act(service)
        return Done(recovered, result, quarantined(conn))

    return run_session(context, body)


@dataclass(frozen=True)
class Organized(Generic[T]):
    recovered: organize_recovery.RecoveryReport  # organize's own unfinished work, settled first
    result: T
    batches: tuple[Summary, ...]  # every batch after ``result``, newest first


def in_organize(
    context: ScanContext, act: Act[T], *, listing: bool = False
) -> Organized[T] | Unfinished | SessionFailed:
    """``act`` on organize's journal, inside the session, or why it did not run; a ``listing``
    is not stopped by other domains' unfinished work. Where organize does not move files the
    page opens no session at all (0012 item 37)."""

    def body(conn: Journal, data_dir: Path) -> Organized[T] | Unfinished:
        recovered = organize_recovery.recover(conn)
        others = set() if listing else pending_domains(conn)
        if others:  # its own was recovered above (0011 item 127)
            return Unfinished(frozenset(others))
        result = act(context, conn)
        return Organized(recovered, result, tuple(summaries(conn)))

    return run_session(context, body)


@dataclass(frozen=True)
class Carried:
    """What came of a confirmed batch."""

    folder: Path
    batch: BatchResult | None  # None: nothing was cleared, and nothing was carried out
    moved: tuple[Planned, ...]  # the moves cleared and carried out as ``batch``
    refused: tuple[Refused, ...]  # at move time (preflight, 0004)
    changed: tuple[Path, ...]  # confirmed, but not in the plan made again, or not unchanged


def no_act(context: ScanContext, conn: Journal) -> None:
    """Nothing: a session that only reads the batches."""
    return None


def plan_folder(folder: Path) -> Act[Plan | FolderRefused]:
    """The plan of ``folder``, or why organize does not sort it."""

    def act(context: ScanContext, conn: Journal) -> Plan | FolderRefused:
        return _plan(folder, context)

    return act


def sort_folder(folder: Path, confirmed: Sequence[Move]) -> Act[Carried | FolderRefused]:
    """The ``confirmed`` moves that ``folder``'s plan, made again, still holds unchanged, checked
    again and carried out as one batch."""

    def act(context: ScanContext, conn: Journal) -> Carried | FolderRefused:
        found = _plan(folder, context)
        if isinstance(found, FolderRefused):
            return found
        still, changed = _still(confirmed, found.moves)
        cleared, refused = check(still, folder, context)
        return _carry(conn, folder, cleared, refused, changed)

    return act


def undo_plan(batch_id: int) -> Act[UndoPlan | UndoRefused]:
    """What undoing ``batch_id`` would move back, or why it cannot be undone."""

    def act(context: ScanContext, conn: Journal) -> UndoPlan | UndoRefused:
        try:
            return plan_undo(conn, batch_id)
        except UndoRefused as refused:
            return refused

    return act


def undo_batch(batch_id: int, confirmed: Sequence[UndoMove]) -> Act[Carried]:
    """The ``confirmed`` moves back that the undo's plan, made again, still holds unchanged,
    checked again and carried out as one undo batch. A batch whose undo was planned stays one
    that can be undone: ``UndoRefused`` is not expected here, and is a task's error."""

    def act(context: ScanContext, conn: Journal) -> Carried:
        found = plan_undo(conn, batch_id)
        still, changed = _still(confirmed, found.moves)
        cleared, refused = check(still, found.folder, context) if still else ((), ())
        undoes = [move.undoes for move in cleared]
        return _carry(conn, found.folder, cleared, refused, changed, undoes)

    return act


def _plan(folder: Path, context: ScanContext) -> Plan | FolderRefused:
    try:
        return plan(folder, context)
    except FolderRefused as refused:
        return refused


def _still(confirmed: Sequence[M], planned: Sequence[M]) -> tuple[list[M], tuple[Path, ...]]:
    """The confirmed moves ``planned`` holds unchanged (same file, same destination), and the
    sources of the others."""
    held = set(planned)
    still = [move for move in confirmed if move in held]
    return still, tuple(move.source for move in confirmed if move not in held)


def _carry(
    conn: Journal,
    folder: Path,
    cleared: Sequence[Planned],
    refused: Sequence[Refused],
    changed: tuple[Path, ...],
    undoes: Sequence[int] | None = None,
) -> Carried:
    if not cleared:
        return Carried(folder, None, (), tuple(refused), changed)
    moves = [(move.source, move.destination) for move in cleared]
    batch = carry_out(conn, folder, moves, undoes=undoes)
    return Carried(folder, batch, tuple(cleared), tuple(refused), changed)


def problem(
    translator: Translator,
    outcome: Unfinished | NoReliableCheck | SessionFailed,
    *,
    no_check: str = "session.no_check",
) -> str:
    """Why a session did not act, in the window's words; ``no_check`` the key of what a page
    says without a reliable open-file check."""
    if isinstance(outcome, Unfinished):
        domains = ", ".join(translator.label(d) for d in Domain if d in outcome.domains)
        return translator.text("session.unfinished", domains=domains)
    if isinstance(outcome, NoReliableCheck):
        return translator.text(no_check)
    failure = translator.label(outcome.failure)
    return translator.text("session.failed", failure=failure, detail=outcome.detail)
