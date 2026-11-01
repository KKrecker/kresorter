"""Recovery of interrupted organize batches, by the disk (decision 0012, item 31).

Every move of a ``pending`` batch is settled by what its two paths hold, whatever its journaled
state, since a move back can have happened after its ``done`` was written: ``done`` when only the
destination holds the file, ``rolled_back`` when only the source does, ``failed`` otherwise,
with a warning naming both paths and what each holds. Recovery renames, overwrites and deletes
nothing, and needs no open-file check. Each move is settled in a transaction of its own and the
batch is closed last, so a recovery interrupted anywhere and run again settles the same.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from safeclean.organize.journal import (
    BatchState,
    MoveState,
    batch_state,
    finish,
    journaled,
    set_move,
    settle,
)
from safeclean.storage.journal import Clock

__all__ = ["INTERRUPTED", "RecoveredBatch", "RecoveryReport", "recover"]

INTERRUPTED = "interrupted; settled by recovery"


@dataclass(frozen=True)
class RecoveredBatch:
    batch_id: int
    state: BatchState
    left: tuple[Path, ...]  # destinations whose move is done: the files still sorted


@dataclass(frozen=True)
class RecoveryReport:
    done: tuple[Path, ...] = ()  # sources, by what their move became
    rolled_back: tuple[Path, ...] = ()
    failed: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()
    batches: tuple[RecoveredBatch, ...] = ()


def recover(conn: sqlite3.Connection, *, now: Clock = time.time_ns) -> RecoveryReport:
    """Settle and close every pending batch, oldest first; move nothing."""
    pending = [
        batch
        for (batch,) in conn.execute(
            "SELECT id FROM move_batches WHERE state = ? ORDER BY id", (BatchState.PENDING,)
        )
    ]
    found: dict[MoveState, list[Path]] = {state: [] for state in MoveState}
    warnings: list[str] = []
    recovered: list[RecoveredBatch] = []
    for batch in pending:
        states: list[MoveState] = []
        left: list[Path] = []
        for move in journaled(conn, batch):
            state, warning = settle(move.source, move.destination, move.file)
            if state is not move.state:
                set_move(conn, move.move_id, state)
            states.append(state)
            found[state].append(move.source)
            if state is MoveState.DONE:
                left.append(move.destination)
            if warning is not None:
                warnings.append(warning)
        outcome = batch_state(states)
        finish(conn, batch, outcome, INTERRUPTED, now)
        recovered.append(RecoveredBatch(batch, outcome, tuple(left)))
    return RecoveryReport(
        done=tuple(found[MoveState.DONE]),
        rolled_back=tuple(found[MoveState.ROLLED_BACK]),
        failed=tuple(found[MoveState.FAILED]),
        warnings=tuple(warnings),
        batches=tuple(recovered),
    )
