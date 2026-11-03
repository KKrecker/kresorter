"""The window's sessions in the journal, run in a task's worker (decision 0014, items 11, 13, 14,
21, 23-25).

A session runs as the CLI's does: the data directory is checked, the lock taken and the journal
opened (``storage.session``); the domain's own unfinished work is recovered first, and
unfinished work of another domain refuses an action before anything is changed (a listing goes
on, as ``quarantine list`` and ``organize list``). A quarantine session needs a reliable
open-file check. Each one ends with the domain's state then: the quarantined files, organize's
batches, the autostart entries. Organize's acts make their plan again inside the session and
carry out only the confirmed moves it still holds unchanged (item 14); an autostart change is
refused by its changer when the entry is no longer the one listed. Recover runs what
``kresorter recover`` runs, for every domain, and looking for unfinished work opens only a
journal that is already there (item 2). What could not run is a value the page shows in its
words (``problem``). No Qt is needed here.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Literal, TypeVar

from kresorter.autostart.changers import changes_for
from kresorter.autostart.changes import XdgChanges
from kresorter.autostart.entries import BrokenEntryError
from kresorter.autostart.journal import ChangeRecovery, ChangeRefusal, ChangeResult, refused
from kresorter.autostart.listing import AutostartContext, list_autostart
from kresorter.autostart.models import AutostartItem, AutostartListing
from kresorter.autostart.registry import RegistryError
from kresorter.autostart.run_changes import RunKeyChanges
from kresorter.core.preflight import Refused, UnreliableCheckerError
from kresorter.core.scanner import ScanContext
from kresorter.organize import recovery as organize_recovery
from kresorter.organize.folders import FolderRefused
from kresorter.organize.journal import Summary, summaries
from kresorter.organize.mover import BatchResult, Planned, carry_out, check
from kresorter.organize.planner import Move, Plan, plan
from kresorter.organize.undo import UndoMove, UndoPlan, UndoRefused, plan_undo
from kresorter.quarantine import recovery as quarantine_recovery
from kresorter.quarantine.journal import QuarantinedItem, quarantined
from kresorter.quarantine.recovery import RecoveryReport
from kresorter.quarantine.service import QuarantineService
from kresorter.storage.data_dir import DataDirError, check_data_dir
from kresorter.storage.pending import Domain, pending_domains
from kresorter.storage.session import JOURNAL_NAME, Journal, SessionFailed, run_session
from kresorter.ui.i18n import Translator

__all__ = [
    "ORDER",
    "Act",
    "Action",
    "Carried",
    "Changed",
    "Done",
    "NoReliableCheck",
    "NotChanged",
    "Organized",
    "Recovered",
    "Unclosed",
    "Unfinished",
    "change_entry",
    "domains",
    "in_organize",
    "in_quarantine",
    "no_act",
    "plan_folder",
    "problem",
    "recover_all",
    "sort_folder",
    "undo_batch",
    "undo_plan",
    "unfinished_work",
]

T = TypeVar("T")
M = TypeVar("M", Move, UndoMove)
Act = Callable[[ScanContext, Journal], T]  # what an organize session does, inside it
Action = Literal["disable", "enable"]
ORDER = (Domain.QUARANTINE, Domain.ORGANIZE, Domain.AUTOSTART)  # as ``kresorter recover`` goes


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


@dataclass(frozen=True)
class Unclosed:
    """An unfinished autostart change that cannot be checked (its entry or flag cannot be read)
    or closed (what it has to move cannot be moved): Recover again once what is there is
    fixed."""

    kind: Literal["unchecked", "unclosed"]
    detail: str


@dataclass(frozen=True)
class NotChanged:
    """A check before the change failed: nothing was journaled, nothing changed."""

    detail: str


@dataclass(frozen=True)
class Changed:
    recovered: ChangeRecovery  # autostart's own unfinished changes, closed first
    result: ChangeResult | NotChanged | Unclosed
    listing: AutostartListing  # the entries after ``result``


def change_entry(
    scan: ScanContext,
    auto: AutostartContext,
    action: Action,
    item: AutostartItem,
    *,
    include_machine: bool = False,
) -> Changed | Unclosed | Unfinished | SessionFailed:
    """``action`` on ``item``, as it was listed, inside the session, as ``autostart disable``
    and ``enable`` with ``--yes`` change it; or why it did not run. The entries after it are
    listed with the machine scope when ``include_machine``."""

    def body(conn: Journal, data_dir: Path) -> Changed | Unclosed | Unfinished:
        changes = changes_for(auto, conn, data_dir)
        recovered = _recover_changes(changes)
        if isinstance(recovered, Unclosed):
            return recovered
        others = pending_domains(conn)
        if others:  # its own was recovered above (0011 item 127)
            return Unfinished(frozenset(others))
        result = _change(changes, action, item)
        return Changed(recovered, result, list_autostart(auto, include_machine=include_machine))

    return run_session(scan, body)


def _change(
    changes: XdgChanges | RunKeyChanges | None, action: Action, item: AutostartItem
) -> ChangeResult | NotChanged | Unclosed:
    if changes is None:  # nothing is written on this system (0011)
        return refused(ChangeRefusal.READ_ONLY, f"{item.source} entries are read-only")
    act = changes.disable if action == "disable" else changes.enable
    try:
        return act(item)
    except (BrokenEntryError, RegistryError) as error:  # read back: left unfinished (item 90)
        return Unclosed("unchecked", str(error))
    except OSError as error:  # a check before acting: nothing is journaled (items 111, 113)
        return NotChanged(str(error))


def _recover_changes(changes: XdgChanges | RunKeyChanges | None) -> ChangeRecovery | Unclosed:
    """The autostart ``recover()``, as ``cli_autostart.recovered`` runs it."""
    try:
        return ChangeRecovery() if changes is None else changes.recover()
    except (BrokenEntryError, RegistryError) as error:
        return Unclosed("unchecked", str(error))
    except OSError as error:  # what it has to move cannot be moved (0011 items 96, 113)
        return Unclosed("unclosed", str(error))


@dataclass(frozen=True)
class Recovered:
    """What Recover closed in each domain, and the domains still unfinished after it."""

    quarantine: RecoveryReport
    organize: organize_recovery.RecoveryReport
    autostart: ChangeRecovery | Unclosed
    left: frozenset[Domain]


def recover_all(scan: ScanContext, auto: AutostartContext) -> Recovered | SessionFailed:
    """What ``kresorter recover`` runs: the quarantine first, then organize's moves, then the
    autostart changes of this platform."""

    def body(conn: Journal, data_dir: Path) -> Recovered:
        found = quarantine_recovery.recover(conn)
        organized = organize_recovery.recover(conn)
        changed = _recover_changes(changes_for(auto, conn, data_dir))
        return Recovered(found, organized, changed, frozenset(pending_domains(conn)))

    return run_session(scan, body)


def unfinished_work(context: ScanContext) -> frozenset[Domain]:
    """The domains with unfinished work in the journal, if there is one: without one, nothing
    is opened and nothing created (items 2, 25). A journal that cannot be read now says
    nothing; the session that needs it will say why."""
    try:
        journal = check_data_dir(context.policy, context.classifier) / JOURNAL_NAME
    except DataDirError:
        return frozenset()
    if not journal.is_file():
        return frozenset()
    found = run_session(context, lambda conn, data_dir: frozenset(pending_domains(conn)))
    return frozenset() if isinstance(found, SessionFailed) else found


def domains(translator: Translator, found: Collection[Domain]) -> str:
    """``found``'s labels, in the order ``kresorter recover`` recovers them."""
    return ", ".join(translator.label(domain) for domain in ORDER if domain in found)


def problem(
    translator: Translator,
    outcome: Unfinished | NoReliableCheck | Unclosed | SessionFailed,
    *,
    no_check: str = "session.no_check",
) -> str:
    """Why a session did not act, in the window's words; ``no_check`` the key of what a page
    says without a reliable open-file check."""
    if isinstance(outcome, Unfinished):
        return translator.text("session.unfinished", domains=domains(translator, outcome.domains))
    if isinstance(outcome, NoReliableCheck):
        return translator.text(no_check)
    if isinstance(outcome, Unclosed):
        return translator.text(f"autostart.{outcome.kind}", detail=outcome.detail)
    failure = translator.label(outcome.failure)
    return translator.text("session.failed", failure=failure, detail=outcome.detail)
