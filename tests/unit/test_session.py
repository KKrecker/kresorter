"""The journal session of whatever acts, the CLI's commands and the window (decision 0014, 11).

``run_session`` checks the data directory before creating anything in it, takes the
single-instance lock, opens the journal there and runs the body with it; why it could not, or
how the body stopped, is a value: the CLI writes its message, the window shows it.
"""

import errno
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from kresorter.core.scanner import ScanContext
from kresorter.storage.lock import InstanceLock
from kresorter.storage.session import (
    JOURNAL_NAME,
    LOCK_NAME,
    SessionFailed,
    SessionFailure,
    run_session,
)
from support.cli import scan_context

Body = Callable[[sqlite3.Connection, Path], int]


def test_the_body_runs_with_the_journal_and_the_data_directory(
    scan: ScanContext, data_dir: Path
) -> None:
    # [0014.11]
    seen: list[tuple[sqlite3.Connection, Path]] = []

    def body(conn: sqlite3.Connection, where: Path) -> str:
        seen.append((conn, where))
        assert conn.execute("SELECT count(*) FROM items").fetchone() == (0,)
        return "done"

    assert run_session(scan, body) == "done"
    ((conn, where),) = seen
    assert where == data_dir
    assert (data_dir / JOURNAL_NAME).is_file()
    assert (data_dir / LOCK_NAME).is_file()
    with pytest.raises(sqlite3.ProgrammingError):  # closed once the body has returned
        conn.execute("SELECT 1")


def test_the_session_is_taken_again_once_ended(scan: ScanContext) -> None:
    # [0014.11]
    def one(conn: sqlite3.Connection, where: Path) -> int:
        return 1

    assert [run_session(scan, one), run_session(scan, one)] == [1, 1]


def never(conn: sqlite3.Connection, where: Path) -> int:
    raise AssertionError("the body must not run")


def test_a_data_directory_in_a_scan_zone_is_refused_before_anything_is_made(
    tmp_path: Path, zone: Path
) -> None:
    # [0014.11]
    inside = scan_context(tmp_path, zone, zone / "kresorter")

    failed = run_session(inside, never)

    assert isinstance(failed, SessionFailed)
    assert failed.failure is SessionFailure.DATA_DIR
    assert failed.detail == f"data directory {zone / 'kresorter'} is inside scan zone {zone}"
    assert list(zone.iterdir()) == []


def test_a_lock_held_elsewhere_is_reported(scan: ScanContext, data_dir: Path) -> None:
    # [0014.11]
    data_dir.mkdir(parents=True)
    with InstanceLock(data_dir / LOCK_NAME):
        failed = run_session(scan, never)

    assert isinstance(failed, SessionFailed)
    assert failed.failure is SessionFailure.LOCKED
    assert failed.detail


@pytest.mark.parametrize("step", ["create", "lock"])
def test_its_own_steps_on_the_data_directory_are_reported(
    scan: ScanContext, data_dir: Path, step: str
) -> None:
    # [0014.11]
    if step == "create":
        data_dir.parent.write_bytes(b"")  # a file where the data directory's parent should be
    else:
        (data_dir / LOCK_NAME).mkdir(parents=True)  # a directory, not a lock file

    failed = run_session(scan, never)

    assert isinstance(failed, SessionFailed)
    assert failed.failure is SessionFailure.DATA_DIR_OS
    assert failed.detail.startswith(("[Errno ", "[WinError "))  # as the system says it


def test_a_journal_that_cannot_be_opened_is_reported(scan: ScanContext, data_dir: Path) -> None:
    # [0014.11]
    (data_dir / JOURNAL_NAME).mkdir(parents=True)  # a directory where the journal should be

    failed = run_session(scan, never)

    assert isinstance(failed, SessionFailed)
    assert failed.failure is SessionFailure.JOURNAL_OPEN
    assert failed.detail


def denied(conn: sqlite3.Connection, where: Path) -> int:
    raise PermissionError(errno.EACCES, "Permission denied", "/elsewhere/app.desktop")


def full(conn: sqlite3.Connection, where: Path) -> int:
    raise sqlite3.OperationalError("database or disk is full")


@pytest.mark.parametrize(
    ("body", "failure", "detail"),
    [
        (
            denied,
            SessionFailure.STOPPED,
            "[Errno 13] Permission denied: '/elsewhere/app.desktop'",
        ),
        (full, SessionFailure.JOURNAL_FAILED, "database or disk is full"),
    ],
    ids=["os-error", "journal-error"],
)
def test_how_the_body_stopped_is_reported(
    scan: ScanContext, body: Body, failure: SessionFailure, detail: str
) -> None:
    # [0014.11]
    assert run_session(scan, body) == SessionFailed(failure, detail)


def test_the_failures_are_pinned() -> None:
    # [0014.11]
    assert [str(failure) for failure in SessionFailure] == [
        "data_dir",
        "locked",
        "data_dir_os",
        "journal_open",
        "stopped",
        "journal_failed",
    ]
