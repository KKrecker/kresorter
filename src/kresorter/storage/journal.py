"""Writing the journal: helpers shared by every domain (pre-step-5 audit, B3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence

from kresorter.storage.transactions import StorageError

Clock = Callable[[], int]
"""Nanoseconds since the Unix epoch, as the journal keeps them (``*_at_ns``); ``time.time_ns``
unless a test gives another. Given to a domain once, never picked by a journal helper (item
121)."""


def insert_row(conn: sqlite3.Connection, sql: str, params: Sequence[object]) -> int:
    """Run one ``INSERT`` and return the id of its row; the caller holds the transaction."""
    row_id = conn.execute(sql, params).lastrowid
    if row_id is None:  # pragma: no cover - sqlite3 always sets it after a successful INSERT
        raise StorageError("no row id after INSERT")
    return row_id
