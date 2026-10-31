"""Journal connection with the settings the safety model relies on (decision 0004)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from safeclean.storage.migrations import migrate
from safeclean.storage.transactions import StorageError, transaction

__all__ = ["BUSY_TIMEOUT_MS", "StorageError", "connect", "transaction"]

BUSY_TIMEOUT_MS = 5000


def connect(path: Path) -> sqlite3.Connection:
    """Open (and migrate) the journal. Autocommit mode: transactions are explicit only.

    Refuses to work without WAL rather than silently degrading durability.
    """
    conn = sqlite3.connect(path, isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        _configure(conn)
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def _configure(conn: sqlite3.Connection) -> None:
    mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if mode != "wal":
        raise StorageError(f"WAL journal mode is unavailable (got {mode!r})")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
