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


def test_v1_journal_gains_atime_and_keeps_its_rows(tmp_path: Path) -> None:
    # v2 adds items.atime_ns (restore puts atime back); v1 rows keep NULL there.
    path = tmp_path / "journal.db"
    raw = sqlite3.connect(path, isolation_level=None)
    migrate(raw, MIGRATIONS[:1])
    add_item(raw, add_operation(raw))
    raw.close()

    upgraded = connect(path)

    assert SCHEMA_VERSION >= 2
    assert pragma(upgraded, "user_version") == SCHEMA_VERSION
    assert upgraded.execute("SELECT size, atime_ns FROM items").fetchall() == [(3, None)]
    upgraded.close()


def test_v2_journal_gains_autostart_changes_and_keeps_its_rows(tmp_path: Path) -> None:
    # v3 adds autostart_changes (decision 0011, item 10); quarantine rows are untouched.
    path = tmp_path / "journal.db"
    raw = sqlite3.connect(path, isolation_level=None)
    migrate(raw, MIGRATIONS[:2])
    add_item(raw, add_operation(raw), atime_ns=7)
    raw.close()

    upgraded = connect(path)

    assert SCHEMA_VERSION == 3
    assert pragma(upgraded, "user_version") == SCHEMA_VERSION
    assert upgraded.execute("SELECT size, atime_ns FROM items").fetchall() == [(3, 7)]
    assert count(upgraded, "autostart_changes") == 0
    upgraded.close()


# --- transactions ------------------------------------------------------------------------------


def _fail_inside_transaction(conn: sqlite3.Connection, error: BaseException) -> None:
    with transaction(conn):
        add_operation(conn)
        raise error


def _nest_transactions(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        add_operation(conn)
        with transaction(conn):
            pass  # pragma: no cover - never reached


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
    with pytest.raises(type(error)):
        _fail_inside_transaction(conn, error)

    assert count(conn, "operations") == 0
    assert not conn.in_transaction


def test_nested_transaction_is_rejected_and_outer_rolled_back(conn: sqlite3.Connection) -> None:
    with pytest.raises(StorageError, match="nested"):
        _nest_transactions(conn)

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


# --- autostart changes (schema v3) -------------------------------------------------------------


def add_change(conn: sqlite3.Connection, **overrides: object) -> int:
    row: dict[str, object] = {
        "action": "disable",
        "source": "xdg_autostart",
        "entry": "/etc/xdg/autostart/app.desktop",
        "location": "/home/a/.config/autostart/app.desktop",
        "digest": "0123456789abcdef0123456789abcdef",
        "value_before": None,
        "value_after": b"[Desktop Entry]\nHidden=true\n",
        "vault_path": None,
        "state": "pending",
        "created_at_ns": 1,
        **overrides,
    }
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    cursor = conn.execute(
        f"INSERT INTO autostart_changes ({columns}) VALUES ({marks})", tuple(row.values())
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def test_autostart_change_is_recorded_with_its_values(conn: sqlite3.Connection) -> None:
    change = add_change(
        conn,
        source="run_key",
        entry="HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\App",
        location="HKCU\\...\\StartupApproved\\Run\\App",
        value_before=bytes(12),
        value_after=b"\x03" + bytes(11),
    )

    row = conn.execute(
        "SELECT value_before, value_after, finished_at_ns, error FROM autostart_changes"
        " WHERE id = ?",
        (change,),
    ).fetchone()
    assert row == (bytes(12), b"\x03" + bytes(11), None, None)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        pytest.param({"action": "delete"}, "CHECK", id="unknown-action"),
        pytest.param({"source": "service"}, "CHECK", id="read-only-source"),
        pytest.param({"source": "launch_agent"}, "CHECK", id="another-read-only-source"),
        pytest.param({"state": "lost"}, "CHECK", id="unknown-state"),
        pytest.param({"entry": ""}, "CHECK", id="empty-entry"),
        pytest.param({"location": ""}, "CHECK", id="empty-location"),
        pytest.param({"location": None}, "NOT NULL", id="no-location"),
        pytest.param({"digest": "0123"}, "CHECK", id="short-digest"),
        pytest.param({"digest": "0123456789ABCDEF0123456789ABCDEF"}, "CHECK", id="upper-digest"),
        pytest.param({"digest": "0123456789abcdef0123456789abcdeg"}, "CHECK", id="non-hex"),
        pytest.param({"value_after": None}, "CHECK", id="nothing-changes-absent"),
        pytest.param({"value_before": b"x", "value_after": b"x"}, "CHECK", id="nothing-changes"),
        pytest.param({"value_after": bytes(65537)}, "CHECK", id="after-too-large"),
        pytest.param(
            {"value_before": bytes(65537), "value_after": None}, "CHECK", id="before-too-large"
        ),
        pytest.param({"value_after": "Hidden=true"}, "cannot store TEXT", id="strict-types"),
        pytest.param({"created_at_ns": None}, "NOT NULL", id="no-created-at"),
    ],
)
def test_autostart_change_constraints(
    conn: sqlite3.Connection, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=message):
        add_change(conn, **overrides)


def test_largest_entry_is_accepted(conn: sqlite3.Connection) -> None:
    add_change(conn, value_before=bytes(65536), value_after=None)

    assert count(conn, "autostart_changes") == 1


def test_autostart_vault_path_is_unique(conn: sqlite3.Connection) -> None:
    add_change(conn, vault_path="/vault/autostart/1")

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        add_change(conn, vault_path="/vault/autostart/1")


def test_changes_without_a_vault_path_do_not_collide(conn: sqlite3.Connection) -> None:
    add_change(conn)
    add_change(conn)

    assert count(conn, "autostart_changes") == 2


@pytest.mark.parametrize("state", ["pending", "done", "failed", "rolled_back"])
def test_all_autostart_change_states_are_accepted(conn: sqlite3.Connection, state: str) -> None:
    add_change(conn, state=state)

    assert count(conn, "autostart_changes") == 1


@pytest.mark.parametrize("action", ["disable", "enable"])
def test_both_actions_are_accepted(conn: sqlite3.Connection, action: str) -> None:
    add_change(conn, action=action)

    assert count(conn, "autostart_changes") == 1
