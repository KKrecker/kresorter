"""The quarantine's journal: the states of operations and items, the updates that move them,
and the check of a file against what was journaled (decision 0004).

The service and the recovery share them; the recovery needs nothing else (pre-step-5 audit,
B7).
"""

from __future__ import annotations

import sqlite3
import stat
from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path

from kresorter.storage.journal import Clock
from kresorter.storage.transactions import transaction


class OperationState(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ItemState(StrEnum):
    PENDING = "pending"
    QUARANTINED = "quarantined"
    RESTORED = "restored"
    ROLLED_BACK = "rolled_back"
    LOST = "lost"
    PURGED = "purged"


@dataclass(frozen=True)
class QuarantinedItem:
    item_id: int
    original: Path
    size: int


def quarantined(conn: sqlite3.Connection) -> tuple[QuarantinedItem, ...]:
    """The files in the quarantine now, by id (``quarantine list``, the window's page)."""
    rows = conn.execute(
        "SELECT id, original_path, size FROM items WHERE state = ? ORDER BY id",
        (ItemState.QUARANTINED,),
    ).fetchall()
    return tuple(QuarantinedItem(item_id, Path(original), size) for item_id, original, size in rows)


def set_item(conn: sqlite3.Connection, item_id: int, state: ItemState) -> None:
    with transaction(conn):
        conn.execute("UPDATE items SET state = ? WHERE id = ?", (state, item_id))


def finish_operation(
    conn: sqlite3.Connection,
    operation_id: int,
    state: OperationState,
    error: str | None,
    *,
    now: Clock,
) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE operations SET state = ?, finished_at_ns = ?, error = ? WHERE id = ?",
            (state, now(), error, operation_id),
        )


class Copy(Enum):
    MATCHES = "matches"
    CHANGED = "changed"
    MISSING = "missing"


def probe(path: Path, size: int, mtime_ns: int) -> Copy:
    """Is the file at ``path`` the one we journaled (regular, same size and mtime_ns)?"""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return Copy.MISSING
    same = (info.st_size, info.st_mtime_ns) == (size, mtime_ns)
    return Copy.MATCHES if stat.S_ISREG(info.st_mode) and same else Copy.CHANGED


def exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True
