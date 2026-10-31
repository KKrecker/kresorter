"""Storage: SQLite journal on a real database file in tmp_path.

Settings (WAL, foreign keys, synchronous=FULL, busy_timeout), versioned migrations that are
all-or-nothing, transactions that roll back on any exception, and schema constraints.
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from safeclean.storage.db import StorageError, connect, transaction
from safeclean.storage.migrations import MIGRATIONS, SCHEMA_VERSION, migrate


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    yield connection
    connection.close()


def pragma(conn: sqlite3.Connection, name: str) -> object:
    return conn.execute(f"PRAGMA {name}").fetchone()[0]


def add_operation(conn: sqlite3.Connection, state: str = "pending") -> int:
    cursor = conn.execute(
        "INSERT INTO operations (kind, state, created_at_ns) VALUES ('quarantine', ?, 1)", (state,)
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def add_item(conn: sqlite3.Connection, operation_id: int, **overrides: object) -> None:
    row: dict[str, object] = {
        "operation_id": operation_id,
        "original_path": "/home/a/Downloads/x.bin",
        "vault_path": f"/vault/{operation_id}/1",
        "size": 3,
        "mtime_ns": 42,
        "mode": 0o100644,
        "digest": None,
        "state": "pending",
        **overrides,
    }
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO items ({columns}) VALUES ({marks})", tuple(row.values()))


def count(conn: sqlite3.Connection, table: str) -> int:
    value = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    assert isinstance(value, int)
    return value


# --- connection settings -----------------------------------------------------------------------


def test_connection_settings(conn: sqlite3.Connection) -> None:
    assert pragma(conn, "journal_mode") == "wal"
    assert pragma(conn, "foreign_keys") == 1
    assert pragma(conn, "synchronous") == 2  # FULL
    assert pragma(conn, "busy_timeout") == 5000


def test_database_without_wal_support_is_rejected() -> None:
    # An in-memory database cannot use WAL; connect must refuse instead of silently degrading.
    with pytest.raises(StorageError, match="WAL"):
        connect(Path(":memory:"))


# --- migrations --------------------------------------------------------------------------------


def test_new_database_is_migrated_to_latest(conn: sqlite3.Connection) -> None:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert pragma(conn, "user_version") == SCHEMA_VERSION == len(MIGRATIONS)
    assert {"operations", "items"} <= tables


def test_reconnect_is_idempotent_and_keeps_data(tmp_path: Path) -> None:
    path = tmp_path / "journal.db"
    first = connect(path)
    with transaction(first):
        add_operation(first)
    first.close()

    second = connect(path)

    assert pragma(second, "user_version") == SCHEMA_VERSION
    assert count(second, "operations") == 1
    second.close()


def test_newer_schema_on_disk_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "journal.db"
    raw = sqlite3.connect(path)
    raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    raw.close()

    with pytest.raises(StorageError, match="newer"):
        connect(path)


def test_failed_migration_leaves_no_trace(tmp_path: Path) -> None:
    raw = sqlite3.connect(tmp_path / "journal.db", isolation_level=None)
    broken = (("CREATE TABLE a (x INTEGER)", "THIS IS NOT SQL"),)

    with pytest.raises(sqlite3.OperationalError):
        migrate(raw, broken)

    assert pragma(raw, "user_version") == 0
    assert raw.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
    raw.close()


def test_migrations_apply_in_order_from_current_version(tmp_path: Path) -> None:
    raw = sqlite3.connect(tmp_path / "journal.db", isolation_level=None)
    steps = (("CREATE TABLE a (x INTEGER)",), ("CREATE TABLE b (y INTEGER)",))
    migrate(raw, steps[:1])

    migrate(raw, steps)

    assert pragma(raw, "user_version") == 2
    raw.close()


# --- transactions ------------------------------------------------------------------------------


def test_transaction_commits_and_is_visible_to_other_connections(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    with transaction(conn):
        add_operation(conn)

    other = connect(tmp_path / "journal.db")
    assert count(other, "operations") == 1
    other.close()


@pytest.mark.parametrize("error", [ValueError("boom"), KeyboardInterrupt()])
def test_transaction_rolls_back_on_any_exception(
    conn: sqlite3.Connection, error: BaseException
) -> None:
    with pytest.raises(type(error)), transaction(conn):
        add_operation(conn)
        raise error

    assert count(conn, "operations") == 0
    assert not conn.in_transaction


def test_nested_transaction_is_rejected_and_outer_rolled_back(conn: sqlite3.Connection) -> None:
    with pytest.raises(StorageError, match="nested"), transaction(conn):
        add_operation(conn)
        with transaction(conn):
            pass  # pragma: no cover - never reached

    assert count(conn, "operations") == 0


def test_transaction_is_immediate(conn: sqlite3.Connection, tmp_path: Path) -> None:
    # BEGIN IMMEDIATE takes the write lock up front: a second writer cannot start.
    other = sqlite3.connect(tmp_path / "journal.db", isolation_level=None, timeout=0)
    with transaction(conn), pytest.raises(sqlite3.OperationalError, match="locked"):
        other.execute("BEGIN IMMEDIATE")
    other.close()


def test_connect_uses_autocommit_mode(conn: sqlite3.Connection) -> None:
    # Transactions are explicit only; the sqlite3 module must not open them implicitly.
    add_operation(conn)

    assert not conn.in_transaction


# --- schema constraints ------------------------------------------------------------------------


def test_item_requires_existing_operation(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        add_item(conn, operation_id=999)


def test_operation_with_items_cannot_be_deleted(conn: sqlite3.Connection) -> None:
    op = add_operation(conn)
    add_item(conn, op)

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("DELETE FROM operations WHERE id = ?", (op,))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        pytest.param({"state": "gone"}, "CHECK", id="unknown-item-state"),
        pytest.param({"size": -1}, "CHECK", id="negative-size"),
        pytest.param({"size": "big"}, "cannot store TEXT", id="strict-types"),
        pytest.param({"original_path": None}, "NOT NULL", id="no-original-path"),
    ],
)
def test_item_constraints(
    conn: sqlite3.Connection, overrides: dict[str, object], message: str
) -> None:
    op = add_operation(conn)

    with pytest.raises(sqlite3.IntegrityError, match=message):
        add_item(conn, op, **overrides)


def test_unknown_operation_state_is_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_operation(conn, state="maybe")


def test_vault_path_is_unique(conn: sqlite3.Connection) -> None:
    op = add_operation(conn)
    add_item(conn, op)

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        add_item(conn, op)


@pytest.mark.parametrize(
    "state", ["pending", "quarantined", "restored", "purged", "rolled_back", "lost"]
)
def test_all_item_states_are_accepted(conn: sqlite3.Connection, state: str) -> None:
    op = add_operation(conn)

    add_item(conn, op, state=state)

    assert count(conn, "items") == 1
