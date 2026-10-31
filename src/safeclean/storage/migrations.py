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

# v2: atime at quarantine time, so restore can put it back (decision 0004, item 6).
_V2: Migration = ("ALTER TABLE items ADD COLUMN atime_ns INTEGER",)

# v3: autostart changes, journaled before they are made (decision 0011, items 10 and 57-62).
# A table of their own: rebuilding `operations` for new kinds would touch its foreign keys.
_V3: Migration = (
    """
    CREATE TABLE autostart_changes (
        id             INTEGER PRIMARY KEY,
        action         TEXT    NOT NULL CHECK (action IN ('disable', 'enable')),
        source         TEXT    NOT NULL CHECK (source IN ('xdg_autostart', 'run_key')),
        entry          TEXT    NOT NULL CHECK (entry <> ''),
        location       TEXT    NOT NULL CHECK (location <> ''),
        digest         TEXT    NOT NULL
                       CHECK (length(digest) = 32 AND digest NOT GLOB '*[^0-9a-f]*'),
        value_before   BLOB    CHECK (length(value_before) <= 65536),
        value_after    BLOB    CHECK (length(value_after) <= 65536),
        vault_path     TEXT    UNIQUE,
        state          TEXT    NOT NULL
                       CHECK (state IN ('pending', 'done', 'failed', 'rolled_back')),
        created_at_ns  INTEGER NOT NULL,
        finished_at_ns INTEGER,
        error          TEXT,
        CHECK (value_before IS NOT value_after)
    ) STRICT
    """,
    "CREATE INDEX autostart_changes_by_state ON autostart_changes (state)",
)

MIGRATIONS: tuple[Migration, ...] = (_V1, _V2, _V3)
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
