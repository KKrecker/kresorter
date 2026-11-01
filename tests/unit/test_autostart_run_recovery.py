"""Reconciling unfinished ``HKCU`` Run changes with the registry (step 4, commit 12b2).

A ``pending`` row is a change interrupted between the journal and its end: the process died,
or the flag could not be read back after a failed write. ``recover()`` reads the flag the row
names and closes the row by what is there: ``done`` if it is the value after the change,
``rolled_back`` if it is the value before, ``failed`` if it is anything else. It only reads the
registry: nothing is redone or undone. An unreadable flag leaves the row pending and raises.
Rows of other sources and finished rows are left as they are. The registry is a fake.
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from fakes import FakeRegistry, RegistryKeys
from safeclean.autostart import changes, run_changes
from safeclean.autostart.models import Source
from safeclean.autostart.registry import Hive, RegistryError, RegValue, ValueKind
from safeclean.autostart.run_keys import APPROVED, RUN, read_run_keys
from safeclean.storage.db import connect
from safeclean.storage.transactions import transaction

DISABLE = b"\x03\x00\x00\x00" + (133_444_736_000_000_000).to_bytes(8, "little")
ENABLE = b"\x02" + bytes(11)
OTHER = b"\x03\x00\x00\x00" + (133_000_000_000_000_000).to_bytes(8, "little")  # someone else's
SYNC = RegValue("Sync", ValueKind.REG_SZ, r"C:\sync.exe")
ENTRY = rf"HKCU\{RUN}\Sync"
LOCATION = rf"HKCU\{APPROVED}\Sync"
DIGEST = "0" * 32
ROLLED_BACK = "interrupted before the registry was written"
FAILED = "the flag is neither as before nor as after the change"


def flag(data: bytes, name: str = "Sync") -> RegValue:
    return RegValue(name, ValueKind.REG_BINARY, data)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    yield connection
    connection.close()


def journal(
    conn: sqlite3.Connection,
    action: str,
    before: bytes | None,
    after: bytes | None,
    *,
    source: Source = Source.RUN_KEY,
    location: str = LOCATION,
) -> int:
    """A ``pending`` row, as a change interrupted right after journaling leaves it."""
    change = changes.Change(action, source, ENTRY, location, DIGEST, before, after)
    with transaction(conn):
        return changes.insert_change(conn, change)


def states(conn: sqlite3.Connection) -> list[tuple[object, ...]]:
    return conn.execute(
        "SELECT state, error, finished_at_ns IS NOT NULL FROM autostart_changes ORDER BY id"
    ).fetchall()


def recover(conn: sqlite3.Connection, keys: RegistryKeys) -> tuple[FakeRegistry, object]:
    registry = FakeRegistry(keys)
    return registry, run_changes.RunKeyChanges(conn, registry).recover()


@pytest.mark.parametrize(
    ("action", "before", "after", "now", "state", "error"),
    [
        ("disable", None, DISABLE, DISABLE, "done", None),
        ("disable", None, DISABLE, None, "rolled_back", ROLLED_BACK),
        ("disable", ENABLE, DISABLE, ENABLE, "rolled_back", ROLLED_BACK),
        ("disable", None, DISABLE, OTHER, "failed", FAILED),
        ("enable", DISABLE, ENABLE, ENABLE, "done", None),
        ("enable", DISABLE, ENABLE, DISABLE, "rolled_back", ROLLED_BACK),
        ("enable", DISABLE, ENABLE, None, "failed", FAILED),
    ],
    ids=[
        "disable-written",
        "disable-not-written",
        "disable-not-written-over-a-flag",
        "disable-overwritten",
        "enable-written",
        "enable-not-written",
        "enable-flag-gone",
    ],
)
def test_a_pending_change_is_closed_by_the_flag_in_the_registry(
    conn: sqlite3.Connection,
    action: str,
    before: bytes | None,
    after: bytes,
    now: bytes | None,
    state: str,
    error: str | None,
) -> None:
    journal(conn, action, before, after)
    keys: RegistryKeys = {(Hive.HKCU, RUN): [SYNC]}
    if now is not None:
        keys = {**keys, (Hive.HKCU, APPROVED): [flag(now)]}

    registry, report = recover(conn, keys)

    assert states(conn) == [(state, error, 1)]
    assert report == changes.ChangeRecovery(**{state: (1,)})
    assert registry.writes == []  # recover() only reads the registry


def test_the_flag_is_found_by_its_name_in_any_case(conn: sqlite3.Connection) -> None:
    journal(conn, "disable", None, DISABLE)

    recover(conn, {(Hive.HKCU, APPROVED): [flag(DISABLE, name="SYNC")]})

    assert states(conn) == [("done", None, 1)]


def test_the_unnamed_flag_is_not_the_one_named_default(conn: sqlite3.Connection) -> None:
    unnamed = journal(conn, "disable", None, DISABLE, location=rf"HKCU\{APPROVED}" + "\\")
    named = journal(conn, "disable", None, DISABLE, location=rf"HKCU\{APPROVED}\(Default)")

    _, report = recover(conn, {(Hive.HKCU, APPROVED): [flag(DISABLE, name="(Default)")]})

    assert report == changes.ChangeRecovery(done=(named,), rolled_back=(unnamed,))


def test_rows_of_other_sources_and_finished_rows_are_left_alone(
    conn: sqlite3.Connection,
) -> None:
    journal(conn, "disable", b"[Desktop Entry]\n", b"x", source=Source.XDG_AUTOSTART)
    failed = journal(conn, "disable", None, DISABLE)
    changes.finish_change(conn, failed, changes.ChangeState.FAILED, "earlier")
    pending = journal(conn, "disable", None, DISABLE)

    _, report = recover(conn, {(Hive.HKCU, APPROVED): [flag(DISABLE)]})

    assert report == changes.ChangeRecovery(done=(pending,))
    assert states(conn) == [("pending", None, 0), ("failed", "earlier", 1), ("done", None, 1)]


def test_an_unreadable_flag_leaves_the_row_pending_and_raises(conn: sqlite3.Connection) -> None:
    journal(conn, "disable", None, DISABLE)
    registry = FakeRegistry({}, denied=[(Hive.HKCU, APPROVED)])

    with pytest.raises(RegistryError, match="access denied"):
        run_changes.RunKeyChanges(conn, registry).recover()

    assert states(conn) == [("pending", None, 0)]


def test_nothing_pending_is_an_empty_report(conn: sqlite3.Connection) -> None:
    registry, report = recover(conn, {})

    assert report == changes.ChangeRecovery()
    assert registry.reads == []


def test_changes_are_allowed_again_once_recovered(conn: sqlite3.Connection) -> None:
    journal(conn, "disable", None, DISABLE)
    registry = FakeRegistry({(Hive.HKCU, RUN): [SYNC]})
    run_keys = run_changes.RunKeyChanges(conn, registry)
    run_keys.recover()
    (item,) = read_run_keys(registry, include_machine=False).items

    result = run_keys.disable(item)

    assert (result.refusal, result.state) == (None, changes.ChangeState.DONE)
