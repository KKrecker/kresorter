"""Versioned schema. Version = ``PRAGMA user_version``; each step is all-or-nothing."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from safeclean.storage.transactions import StorageError, transaction

Migration = tuple[str, ...]

_V1: Migration = (
    """
    CREATE TABLE operations (
        id             INTEGER PRIMARY KEY,
        kind           TEXT    NOT NULL CHECK (kind IN ('quarantine', 'restore', 'purge')),
        state          TEXT    NOT NULL
                       CHECK (state IN ('pending', 'done', 'failed', 'rolled_back')),
        created_at_ns  INTEGER NOT NULL,
        finished_at_ns INTEGER,
        error          TEXT
    ) STRICT
    """,
    """
    CREATE TABLE items (
        id                  INTEGER PRIMARY KEY,
        operation_id        INTEGER NOT NULL REFERENCES operations (id) ON DELETE RESTRICT,
        restore_operation_id INTEGER REFERENCES operations (id) ON DELETE RESTRICT,
        purge_operation_id  INTEGER REFERENCES operations (id) ON DELETE RESTRICT,
        original_path       TEXT    NOT NULL,
        vault_path          TEXT    NOT NULL UNIQUE,
        size                INTEGER NOT NULL CHECK (size >= 0),
        mtime_ns            INTEGER NOT NULL,
        mode                INTEGER NOT NULL,
        digest              TEXT,
        state               TEXT    NOT NULL CHECK (state IN (
                                'pending', 'quarantined', 'restored', 'purged',
                                'rolled_back', 'lost'))
    ) STRICT
    """,
    "CREATE INDEX items_by_operation ON items (operation_id)",
    "CREATE INDEX items_by_state ON items (state)",
)

MIGRATIONS: tuple[Migration, ...] = (_V1,)
SCHEMA_VERSION = len(MIGRATIONS)


def migrate(conn: sqlite3.Connection, migrations: Sequence[Migration] = MIGRATIONS) -> int:
    """Apply pending migrations in order, one transaction each. Returns the final version.

    ``conn`` must be in autocommit mode (``isolation_level=None``).
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > len(migrations):
        raise StorageError(f"journal schema v{current} is newer than supported v{len(migrations)}")
    for version in range(current, len(migrations)):
        with transaction(conn):
            for statement in migrations[version]:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version + 1}")
    return len(migrations)
