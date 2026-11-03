"""Explicit, all-or-nothing transactions."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager


class StorageError(Exception):
    """The journal cannot be used safely (missing WAL, newer schema, misuse)."""


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` ... ``COMMIT``; ``ROLLBACK`` on any exception, including
    KeyboardInterrupt. The write lock is taken up front, so a transaction never fails
    halfway because another writer got there first.
    """
    if conn.in_transaction:
        raise StorageError("nested transactions are not supported")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
