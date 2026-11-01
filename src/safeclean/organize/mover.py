"""Organize's mover (decision 0012, items 19 and 25-28).

``check`` takes every planned file again right before the batch, as the quarantine does (0004
item 5): allowed by the policy and not open, the size and ``mtime_ns`` of the plan, a parent not
swapped for a link, on the folder's device, and a destination still free in a real directory on
that device. A file that fails is refused; the others form the batch.

``carry_out`` journals the batch and every move ``pending`` before anything is made or moved,
then, move by move, makes the category directory (default mode; an existing one is used as it
is), checks the destination once more and renames: never a copy, never over a file. A move that
fails stops the batch: no later move is tried, and the moved files go back newest first, each
one tried even when one before it could not go back, never over a file that appeared at its
source. Where a rename that raised left its file is asked of the disk (``journal.settle``). An
exception that is not an ``OSError`` is raised again after the rollback; one raised by the
rollback itself stops everything, the batch left ``pending`` for recovery.
"""

from __future__ import annotations

import errno
import os
import sqlite3
import stat
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from safeclean.core.models import FileEntry
from safeclean.core.preflight import Candidate, Preflight, RefusalReason, Refused
from safeclean.core.scanner import ScanContext
from safeclean.organize.journal import (
    BatchState,
    MoveState,
    batch_state,
    begin,
    finish,
    identity,
    set_move,
    set_moves,
    settle,
)
from safeclean.storage.journal import Clock

__all__ = ["BatchResult", "BatchState", "Planned", "carry_out", "check"]

Rename = Callable[[Path, Path], None]


class Planned(Protocol):
    """A move as planned: from where to where, and the file as the plan saw it."""

    @property
    def source(self) -> Path: ...
    @property
    def destination(self) -> Path: ...
    @property
    def size(self) -> int: ...
    @property
    def mtime_ns(self) -> int: ...


P = TypeVar("P", bound=Planned)


@dataclass(frozen=True)
class BatchResult:
    batch_id: int
    state: BatchState
    left: tuple[Path, ...]  # destinations whose move stays done although the batch stopped
    error: str | None  # why the batch stopped


def check(
    moves: Sequence[P], folder: Path, context: ScanContext
) -> tuple[tuple[P, ...], tuple[Refused, ...]]:
    """The moves still cleared right before the batch, in order, and the refusals."""
    preflight = Preflight(context.policy, context.open_files)
    device = folder.lstat().st_dev
    cleared: list[P] = []
    refused: list[Refused] = []
    for move in moves:
        refusal = _refusal(preflight, move, device)
        if refusal is None:
            cleared.append(move)
        else:
            refused.append(refusal)
    return tuple(cleared), tuple(refused)


def carry_out(
    conn: sqlite3.Connection,
    folder: Path,
    moves: Sequence[tuple[Path, Path]],
    *,
    rename: Rename = os.rename,
    now: Clock = time.time_ns,
) -> BatchResult:
    """Move each source to its destination, journaled, all or nothing as far as the disk
    allows. Raises OSError, before anything is journaled, when a source cannot be looked at."""
    if not moves:
        raise ValueError("a batch needs at least one move")
    device = folder.lstat().st_dev
    files = [identity(source) for source, _ in moves]
    batch, ids = begin(
        conn, folder, [(*move, file) for move, file in zip(moves, files, strict=True)], now
    )
    states = [MoveState.PENDING] * len(moves)
    error: str | None = None
    raised: BaseException | None = None
    for i, (source, destination) in enumerate(moves):
        try:
            _make_room(destination, device)
            rename(source, destination)
        except BaseException as exc:
            states[i], _ = settle(source, destination, files[i])
            set_move(conn, ids[i], states[i])
            error = str(exc) or type(exc).__name__
            raised = None if isinstance(exc, OSError) else exc
            break
        states[i] = MoveState.DONE
        set_move(conn, ids[i], MoveState.DONE)
    if error is None:
        finish(conn, batch, BatchState.DONE, None, now)
        return BatchResult(batch, BatchState.DONE, (), None)
    never_tried = [i for i, state in enumerate(states) if state is MoveState.PENDING]
    set_moves(conn, [ids[i] for i in never_tried], MoveState.ROLLED_BACK)
    for i in never_tried:
        states[i] = MoveState.ROLLED_BACK
    for i in reversed(range(len(moves))):
        source, destination = moves[i]
        if states[i] is not MoveState.DONE or os.path.lexists(source):
            continue  # not moved, or a newcomer at its source: never overwritten
        try:
            rename(destination, source)
        except OSError:
            states[i], _ = settle(source, destination, files[i])
        else:
            states[i] = MoveState.ROLLED_BACK
        set_move(conn, ids[i], states[i])
    outcome = batch_state(states)
    finish(conn, batch, outcome, error, now)
    if raised is not None:
        raise raised
    left = tuple(moves[i][1] for i, state in enumerate(states) if state is MoveState.DONE)
    return BatchResult(batch, outcome, left, error)


def _refusal(preflight: Preflight, move: Planned, device: int) -> Refused | None:
    source = move.source
    result = preflight.check(Candidate(FileEntry(source, move.size, move.mtime_ns)))
    if isinstance(result, Refused):
        return result
    if result.stat.st_dev != device:
        return Refused(source, RefusalReason.CROSS_DEVICE)
    parent = move.destination.parent
    try:
        info = parent.lstat()
    except FileNotFoundError:
        pass  # a category directory the batch makes
    except OSError as error:
        return Refused(source, RefusalReason.UNREADABLE, detail=f"{parent}: {_why(error)}")
    else:
        if not stat.S_ISDIR(info.st_mode):
            return Refused(source, RefusalReason.CONFLICT, detail=f"{parent}: not a directory")
        if info.st_dev != device:
            return Refused(source, RefusalReason.CROSS_DEVICE, detail=str(parent))
    try:
        move.destination.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        return Refused(source, RefusalReason.CONFLICT, detail=_why(error))
    return Refused(source, RefusalReason.CONFLICT, detail=str(move.destination))


def _make_room(destination: Path, device: int) -> None:
    """Make the destination's directory if it is missing, then raise OSError unless it is a
    real directory on the folder's device and the destination is free."""
    parent = destination.parent
    parent.mkdir(exist_ok=True)
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise NotADirectoryError(errno.ENOTDIR, "not a directory", str(parent))
    if info.st_dev != device:
        raise OSError(errno.EXDEV, "on another device than the folder", str(parent))
    if os.path.lexists(destination):
        raise FileExistsError(errno.EEXIST, "taken since the check", str(destination))


def _why(error: OSError) -> str:
    return error.strerror or str(error)
