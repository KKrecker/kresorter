"""Writing the journal: helpers shared by every domain (pre-step-5 audit, B3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from safeclean.storage.transactions import StorageError


def insert_row(conn: sqlite3.Connection, sql: str, params: Sequence[object]) -> int:
    """Run one ``INSERT`` and return the id of its row; the caller holds the transaction."""
    row_id = conn.execute(sql, params).lastrowid
    if row_id is None:  # pragma: no cover - sqlite3 always sets it after a successful INSERT
        raise StorageError("no row id after INSERT")
    return row_id
