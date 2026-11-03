"""Undo (decision 0012, items 29 and 30): the plan that moves back what a batch moved.

Only the batch's ``done`` moves that no ``done`` move undoes yet are taken, in journal order: a
``failed`` move is the user's to decide, and an undo that stopped leaves the rest to the next.
An undo batch cannot itself be undone (organize again instead), and a pending batch is
recovered first: until then the journal does not say where its files are.

What is at a destination goes back if it is a regular file, even changed since the move: a
document edited after sorting is still the user's document, and the plan takes it as it is now
(preflight checks it against this plan, item 19). A missing file, a link or a directory stays,
and a source taken by a newcomer, or that cannot be looked at, is never overwritten. The plan
reads the disk and changes nothing; the mover carries it out as a batch of kind ``undo``.
"""

from __future__ import annotations

import sqlite3
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from kresorter.organize.journal import BatchKind, BatchState, batch, undoable
from kresorter.organize.planner import Stay, StayReason

__all__ = ["UndoMove", "UndoPlan", "UndoReason", "UndoRefused", "plan_undo"]


class UndoReason(StrEnum):
    NOT_FOUND = "not_found"
    UNDO_BATCH = "undo_batch"
    PENDING = "pending"


class UndoRefused(Exception):
    """The batch cannot be undone at all."""

    def __init__(self, batch_id: int, reason: UndoReason) -> None:
        super().__init__(f"batch {batch_id}: {reason}")
        self.batch_id = batch_id
        self.reason = reason


@dataclass(frozen=True)
class UndoMove:
    """A file to move back, with the size and ``mtime_ns`` it has now (checked again, item 19)."""

    source: Path  # where the batch put it
    destination: Path  # where it was
    size: int
    mtime_ns: int
    undoes: int  # the move it reverses


@dataclass(frozen=True)
class UndoPlan:
    batch_id: int
    folder: Path
    moves: tuple[UndoMove, ...]  # in journal order
    stays: tuple[Stay, ...]  # likewise; each one where the batch put it


def plan_undo(conn: sqlite3.Connection, batch_id: int) -> UndoPlan:
    """What undoing ``batch_id`` would move back, and what stays. Raises UndoRefused."""
    found = batch(conn, batch_id)
    if found is None:
        raise UndoRefused(batch_id, UndoReason.NOT_FOUND)
    if found.kind is BatchKind.UNDO:
        raise UndoRefused(batch_id, UndoReason.UNDO_BATCH)
    if found.state is BatchState.PENDING:
        raise UndoRefused(batch_id, UndoReason.PENDING)
    moves: list[UndoMove] = []
    stays: list[Stay] = []
    for move in undoable(conn, batch_id):
        try:
            info = move.destination.lstat()
        except FileNotFoundError:
            stays.append(Stay(move.destination, StayReason.MISSING))
            continue
        except OSError as error:
            stays.append(Stay(move.destination, StayReason.MISSING, _why(error)))
            continue
        if not stat.S_ISREG(info.st_mode):
            stays.append(Stay(move.destination, StayReason.NOT_REGULAR))
            continue
        taken = _taken(move.source)
        if taken is not None:
            stays.append(Stay(move.destination, StayReason.CONFLICT, taken))
            continue
        moves.append(
            UndoMove(move.destination, move.source, info.st_size, info.st_mtime_ns, move.move_id)
        )
    return UndoPlan(batch_id, found.folder, tuple(moves), tuple(stays))


def _taken(source: Path) -> str | None:
    """None when nothing is at ``source``; otherwise why it counts as taken ("" for a file)."""
    try:
        source.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        return _why(error)
    return ""


def _why(error: OSError) -> str:
    return error.strerror or str(error)
