"""The files in the quarantine, from the journal, for the CLI and the window (0014, item 12)."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy
from kresorter.core.models import FileEntry
from kresorter.core.preflight import Candidate
from kresorter.quarantine.journal import QuarantinedItem, quarantined
from kresorter.quarantine.service import QuarantineService
from kresorter.storage.db import connect
from support.files import write
from support.host import host_classifier


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    yield connection
    connection.close()


@pytest.fixture
def service(conn: sqlite3.Connection, tmp_path: Path, zone: Path) -> QuarantineService:
    policy = make_policy(tmp_path, default_roots=[zone], app_data_dir=tmp_path / "data" / "sc")
    return QuarantineService(
        conn,
        policy=policy,
        open_files=FakeOpenFiles(),
        classifier=host_classifier([]),
    )


def put(service: QuarantineService, path: Path, data: bytes) -> int:
    write(path, data)
    info = path.lstat()
    entry = FileEntry(path=path, size=info.st_size, mtime_ns=info.st_mtime_ns)
    return service.quarantine([Candidate(entry=entry)]).moved[0].item_id


def test_an_empty_journal_has_nothing_quarantined(conn: sqlite3.Connection) -> None:
    # [0014.12]
    assert quarantined(conn) == ()


def test_the_files_still_quarantined_by_id(
    conn: sqlite3.Connection, service: QuarantineService, zone: Path
) -> None:
    # [0014.12]
    first = put(service, zone / "b.log", b"12345")
    second = put(service, zone / "a.log", b"12")
    third = put(service, zone / "c.log", b"1")
    service.restore([second])

    assert quarantined(conn) == (
        QuarantinedItem(first, zone / "b.log", 5),
        QuarantinedItem(third, zone / "c.log", 1),
    )
