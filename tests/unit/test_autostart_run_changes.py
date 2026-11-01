"""Disabling and enabling an HKCU Run value by its StartupApproved flag (step 4, commit 12a4b).

The Run value itself is never written: the flag in ``Explorer\\StartupApproved\\Run`` is, with
the bytes the Task Manager writes (``03 00 00 00`` and the FILETIME of the change to disable,
``02`` and zeros to enable). A missing flag means enabled; enabling never deletes a value, it
writes ``02``. The value must still be exactly as listed, found again by its digest; each
change is journaled before the registry is written, and a failure is rolled back. Only HKCU
Run values can change. The registry is a fake: nothing real is read or written.
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from fakes import FakeRegistry, RegistryKeys
from safeclean.autostart import run_changes
from safeclean.autostart.changes import ChangeRefusal, ChangeResult, ChangeState
from safeclean.autostart.models import (
    AutostartItem,
    AutostartListing,
    Scope,
    Source,
    entry_digest,
)
from safeclean.autostart.registry import Hive, RegistryError, RegValue, ValueKind
from safeclean.autostart.run_keys import APPROVED, RUN, RUN_ONCE, read_run_keys
from safeclean.storage.db import connect

NOW = 1_700_000_000 * 1_000_000_000  # 2023-11-14T22:13:20Z, in ns since the Unix epoch
FILETIME = (133_444_736_000_000_000).to_bytes(8, "little")  # the same instant, Windows time
DISABLE = b"\x03\x00\x00\x00" + FILETIME
ENABLE = b"\x02" + bytes(11)
SYNC = RegValue("Sync", ValueKind.REG_SZ, r"C:\sync.exe")
ENTRY = rf"HKCU\{RUN}\Sync"
LOCATION = rf"HKCU\{APPROVED}\Sync"
COLUMNS = (
    "action, source, entry, location, digest, value_before, value_after, vault_path, state,"
    " error, finished_at_ns IS NOT NULL"
)

Row = tuple[object, ...]


def flag(data: bytes, name: str = "Sync") -> RegValue:
    return RegValue(name, ValueKind.REG_BINARY, data)


def now() -> int:
    return NOW


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    yield connection
    connection.close()


def setup(
    conn: sqlite3.Connection, keys: RegistryKeys, *, write_error: BaseException | None = None
) -> tuple[FakeRegistry, run_changes.RunKeyChanges]:
    registry = FakeRegistry(keys, write_error=write_error)
    return registry, run_changes.RunKeyChanges(conn, registry, now=now)


def listed(registry: FakeRegistry, *, include_machine: bool = False) -> tuple[AutostartItem, ...]:
    return read_run_keys(registry, include_machine=include_machine).items


def only(registry: FakeRegistry) -> AutostartItem:
    (item,) = listed(registry)
    return item


def rows(conn: sqlite3.Connection) -> list[Row]:
    return conn.execute(f"SELECT {COLUMNS} FROM autostart_changes ORDER BY id").fetchall()


# --- disable -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "before", [None, ENABLE, b"\x06" + bytes(11)], ids=["no-flag", "enabled", "enabled-06"]
)
def test_disable_writes_the_flag_the_task_manager_writes(
    conn: sqlite3.Connection, before: bytes | None
) -> None:
    keys: RegistryKeys = {(Hive.HKCU, RUN): [SYNC]}
    if before is not None:
        keys = {**keys, (Hive.HKCU, APPROVED): [flag(before)]}
    registry, changes = setup(conn, keys)
    item = only(registry)

    result = changes.disable(item)

    assert result == ChangeResult(1, ChangeState.DONE)
    assert registry.writes == [(APPROVED, flag(DISABLE))]
    assert registry.values(Hive.HKCU, RUN) == [SYNC]  # the Run value is never written
    after = only(registry)
    assert (after.location, after.enabled, after.command) == (item.location, False, item.command)
    assert rows(conn) == [
        ("disable", "run_key", ENTRY, LOCATION, item.digest, before, DISABLE, None, "done", None, 1)
    ]


def test_the_journal_row_exists_before_the_registry_is_written(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, changes = setup(conn, {(Hive.HKCU, RUN): [SYNC]})
    seen: list[list[Row]] = []
    write = registry.set_user_value

    def watching(key: str, value: RegValue) -> None:
        seen.append(conn.execute("SELECT state FROM autostart_changes").fetchall())
        write(key, value)

    monkeypatch.setattr(registry, "set_user_value", watching)

    changes.disable(only(registry))

    assert seen == [[("pending",)]]


def test_the_default_value_is_told_apart_from_one_named_default(conn: sqlite3.Connection) -> None:
    # Both are listed as "(Default)"; the digest says which one was meant.
    named = RegValue("(Default)", ValueKind.REG_SZ, r"C:\named.exe")
    default = RegValue("", ValueKind.REG_SZ, r"C:\default.exe")
    registry, changes = setup(conn, {(Hive.HKCU, RUN): [named, default]})
    (item,) = [i for i in listed(registry) if i.command == r"C:\default.exe"]

    changes.disable(item)

    assert registry.writes == [(APPROVED, flag(DISABLE, name=""))]


# --- enable --------------------------------------------------------------------------------------


@pytest.mark.parametrize("before", [DISABLE, b"\x07" + bytes(11)], ids=["disabled", "disabled-07"])
def test_enable_writes_the_flag_the_task_manager_writes(
    conn: sqlite3.Connection, before: bytes
) -> None:
    # Disabled by the Task Manager, not by safeclean: the flag is Windows' own switch, so
    # enabling it edits nothing else (unlike item 74).
    keys: RegistryKeys = {(Hive.HKCU, RUN): [SYNC], (Hive.HKCU, APPROVED): [flag(before)]}
    registry, changes = setup(conn, keys)
    item = only(registry)

    result = changes.enable(item)

    assert result == ChangeResult(1, ChangeState.DONE)
    assert registry.writes == [(APPROVED, flag(ENABLE))]
    assert only(registry).enabled is True
    assert rows(conn) == [
        ("enable", "run_key", ENTRY, LOCATION, item.digest, before, ENABLE, None, "done", None, 1)
    ]


def test_disable_and_enable_never_delete_the_flag(conn: sqlite3.Connection) -> None:
    registry, changes = setup(conn, {(Hive.HKCU, RUN): [SYNC]})

    for _ in range(2):
        assert changes.disable(only(registry)).state is ChangeState.DONE
        assert changes.enable(only(registry)).state is ChangeState.DONE

    assert registry.values(Hive.HKCU, APPROVED) == [flag(ENABLE)]
    assert [row[0] for row in rows(conn)] == ["disable", "enable", "disable", "enable"]


# --- refusals: nothing written, nothing journaled ------------------------------------------------


def assert_refused(
    conn: sqlite3.Connection, registry: FakeRegistry, result: ChangeResult, refusal: ChangeRefusal
) -> None:
    assert (result.change_id, result.state, result.refusal) == (None, None, refusal)
    assert result.detail
    assert registry.writes == []
    assert rows(conn) == []


@pytest.mark.parametrize("action", ["disable", "enable"])
def test_run_once_and_machine_values_are_read_only(conn: sqlite3.Connection, action: str) -> None:
    keys: RegistryKeys = {
        (Hive.HKCU, RUN_ONCE): [RegValue("Once", ValueKind.REG_SZ, r"C:\once.exe")],
        (Hive.HKLM, RUN): [RegValue("Agent", ValueKind.REG_SZ, r"C:\agent.exe")],
        (Hive.HKLM, APPROVED): [flag(DISABLE, name="Agent")],
    }
    registry, changes = setup(conn, keys)
    items = listed(registry, include_machine=True)
    assert {(i.source, i.scope) for i in items} == {
        (Source.RUN_ONCE_KEY, Scope.USER),
        (Source.RUN_KEY, Scope.SYSTEM),
    }

    for item in items:
        result = getattr(changes, action)(item)
        assert_refused(conn, registry, result, ChangeRefusal.READ_ONLY)


def test_other_sources_are_not_run_values(conn: sqlite3.Connection, tmp_path: Path) -> None:
    registry, changes = setup(conn, {})
    xdg = AutostartItem(
        source=Source.XDG_AUTOSTART,
        scope=Scope.USER,
        name="app",
        command="/usr/bin/app",
        location=str(tmp_path / "app.desktop"),
        enabled=True,
        digest=entry_digest(b"app"),
    )

    assert_refused(conn, registry, changes.disable(xdg), ChangeRefusal.READ_ONLY)


@pytest.mark.parametrize(
    ("before", "action"), [(None, "enable"), (DISABLE, "disable")], ids=["enabled", "disabled"]
)
def test_a_value_already_in_that_state_is_refused(
    conn: sqlite3.Connection, before: bytes | None, action: str
) -> None:
    keys: RegistryKeys = {(Hive.HKCU, RUN): [SYNC]}
    if before is not None:
        keys = {**keys, (Hive.HKCU, APPROVED): [flag(before)]}
    registry, changes = setup(conn, keys)

    assert_refused(conn, registry, getattr(changes, action)(only(registry)), ChangeRefusal.ALREADY)


@pytest.mark.parametrize(
    "now_keys",
    [
        {(Hive.HKCU, RUN): [RegValue("Sync", ValueKind.REG_SZ, r"C:\evil.exe")]},
        {(Hive.HKCU, RUN): [SYNC], (Hive.HKCU, APPROVED): [flag(DISABLE)]},
        {(Hive.HKCU, RUN): []},
    ],
    ids=["value-changed", "flag-changed", "value-gone"],
)
def test_a_value_changed_since_it_was_listed_is_refused(
    conn: sqlite3.Connection, now_keys: RegistryKeys
) -> None:
    item = only(FakeRegistry({(Hive.HKCU, RUN): [SYNC]}))
    registry, changes = setup(conn, now_keys)

    assert_refused(conn, registry, changes.disable(item), ChangeRefusal.CHANGED)


def test_a_value_changed_right_after_the_check_is_refused(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The listing is read again first; the value written is found once more by its digest.
    item = only(FakeRegistry({(Hive.HKCU, RUN): [SYNC]}))
    stale = AutostartListing((item,), ())
    evil = RegValue("Sync", ValueKind.REG_SZ, r"C:\evil.exe")
    registry, changes = setup(conn, {(Hive.HKCU, RUN): [evil]})

    def read_before_the_edit(registry: object, *, include_machine: bool) -> AutostartListing:
        return stale

    monkeypatch.setattr(run_changes, "read_run_keys", read_before_the_edit)

    assert_refused(conn, registry, changes.disable(item), ChangeRefusal.CHANGED)


def test_unfinished_work_in_the_journal_is_refused(conn: sqlite3.Connection) -> None:
    registry, changes = setup(conn, {(Hive.HKCU, RUN): [SYNC]})
    conn.execute(
        "INSERT INTO operations (kind, state, created_at_ns) VALUES ('quarantine', 'pending', 1)"
    )

    result = changes.disable(only(registry))

    assert (result.change_id, result.state, result.refusal) == (None, None, ChangeRefusal.PENDING)
    assert (registry.writes, rows(conn)) == ([], [])


# --- failures ------------------------------------------------------------------------------------


def test_a_failed_write_is_rolled_back(conn: sqlite3.Connection) -> None:
    error = RegistryError("Access is denied")
    registry, changes = setup(conn, {(Hive.HKCU, RUN): [SYNC]}, write_error=error)
    item = only(registry)

    result = changes.disable(item)

    assert (result.change_id, result.state, result.refusal) == (1, ChangeState.ROLLED_BACK, None)
    assert result.detail == "Access is denied"
    assert listed(registry) == (item,)
    assert [row[8:10] for row in rows(conn)] == [("rolled_back", "Access is denied")]


def test_an_interrupted_write_is_rolled_back_and_raised(conn: sqlite3.Connection) -> None:
    registry, changes = setup(conn, {(Hive.HKCU, RUN): [SYNC]}, write_error=KeyboardInterrupt())
    item = only(registry)

    with pytest.raises(KeyboardInterrupt):
        changes.disable(item)

    assert [row[8:10] for row in rows(conn)] == [("rolled_back", "KeyboardInterrupt")]
    assert listed(registry) == (item,)
