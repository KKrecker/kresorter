"""Unfinished work in the journal, by domain (decision 0011, items 62, 99, 125).

Each domain journals into a table of its own; a ``pending`` row in it is unfinished work of that
domain. The set says which recoveries are owed, and is empty when none is.
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from safeclean.storage.db import connect
from safeclean.storage.pending import Domain, pending_domains

OPERATION = "INSERT INTO operations (kind, state, created_at_ns) VALUES ('quarantine', ?, 1)"
CHANGE = (
    "INSERT INTO autostart_changes (action, source, entry, location, digest, value_after, state,"
    " created_at_ns) VALUES ('disable', 'xdg_autostart', 'app', '/a.desktop', ?, x'01', ?, 1)"
)
BATCH = (
    "INSERT INTO move_batches (kind, folder, state, created_at_ns) VALUES ('organize', '/d', ?, 1)"
)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(tmp_path / "journal.db")
    yield conn
    conn.close()


def test_an_empty_journal_owes_nothing(conn: sqlite3.Connection) -> None:
    assert pending_domains(conn) == set()


def test_finished_work_is_not_pending(conn: sqlite3.Connection) -> None:
    conn.execute(OPERATION, ("done",))
    conn.execute(CHANGE, ("0" * 32, "rolled_back"))

    assert pending_domains(conn) == set()


@pytest.mark.parametrize(
    ("operation", "change", "domains"),
    [
        ("pending", "done", {Domain.QUARANTINE}),
        ("done", "pending", {Domain.AUTOSTART}),
        ("pending", "pending", {Domain.QUARANTINE, Domain.AUTOSTART}),
    ],
    ids=["quarantine", "autostart", "both"],
)
def test_each_domain_with_a_pending_row_is_named(
    conn: sqlite3.Connection, operation: str, change: str, domains: set[Domain]
) -> None:
    conn.execute(OPERATION, (operation,))
    conn.execute(CHANGE, ("0" * 32, change))

    assert pending_domains(conn) == domains


@pytest.mark.parametrize("state", ["done", "rolled_back", "failed"])
def test_a_finished_organize_batch_is_not_pending(conn: sqlite3.Connection, state: str) -> None:
    # [0012.32]
    conn.execute(BATCH, (state,))

    assert pending_domains(conn) == set()


def test_a_pending_organize_batch_is_unfinished_organize_work(conn: sqlite3.Connection) -> None:
    # [0012.32] the batch, whatever its moves say: recovery settles every one of them
    conn.execute(BATCH, ("pending",))
    conn.execute(OPERATION, ("pending",))

    assert pending_domains(conn) == {Domain.QUARANTINE, Domain.ORGANIZE}


def test_a_domain_is_named_by_its_command() -> None:
    # [0012.32]
    assert [str(domain) for domain in Domain] == ["quarantine", "autostart", "organize"]
