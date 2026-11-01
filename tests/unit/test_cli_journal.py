"""The journal session shared by the commands that act (decision 0011, items 101, 112, 114).

``with_journal`` names the data directory only for what it does there itself: creating it and
taking the lock. An ``OSError`` raised by the body of a command is the body's own: it is
reported with its reason, never as a data directory that could not be used. A journal that
fails in the middle of a command leaves an end that cannot be trusted: exit 3, naming the
command that recovers the domain.
"""

import errno
import io
import sqlite3
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy
from safeclean import cli_journal
from safeclean.core.heuristics import JunkClassifier, default_rules
from safeclean.core.scanner import ScanContext

RECOVER = "safeclean thing recover"  # the domain's own command, passed in by it


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data" / "safeclean"


@pytest.fixture
def scan(tmp_path: Path, data_dir: Path) -> ScanContext:
    # As in test_cli_quarantine: tmp_path is under /tmp, which "posix-temp" marks as junk.
    rules = [r for r in default_rules() if r.id != "posix-temp"]
    zone = tmp_path / "zone"
    policy = make_policy(tmp_path, tmp_path / "system", default_roots=[zone], app_data_dir=data_dir)
    return ScanContext(policy, FakeOpenFiles(), JunkClassifier(rules, platform="linux"), True)


def full(conn: sqlite3.Connection, data_dir: Path) -> int:
    raise sqlite3.OperationalError("database or disk is full")


def denied(conn: sqlite3.Connection, data_dir: Path) -> int:
    raise PermissionError(errno.EACCES, "Permission denied", "/elsewhere/app.desktop")


def test_an_os_error_of_the_body_is_reported_with_its_reason_only(scan: ScanContext) -> None:
    err = io.StringIO()

    code = cli_journal.with_journal(scan, err, denied, recover=RECOVER)

    assert code == 3
    assert err.getvalue() == (
        "safeclean: stopped: [Errno 13] Permission denied: '/elsewhere/app.desktop'\n"
    )


@pytest.mark.parametrize("step", ["create", "lock"])
def test_its_own_steps_name_the_data_directory(
    scan: ScanContext, data_dir: Path, step: str
) -> None:
    if step == "create":
        data_dir.parent.write_bytes(b"")  # a file where the data directory's parent should be
    else:
        (data_dir / cli_journal.LOCK_NAME).mkdir(parents=True)  # a directory, not a lock file
    ran: list[Path] = []

    def body(conn: sqlite3.Connection, where: Path) -> int:
        ran.append(where)
        return 0

    err = io.StringIO()

    code = cli_journal.with_journal(scan, err, body, recover=RECOVER)

    assert (code, ran) == (3, [])
    assert err.getvalue().startswith("safeclean: cannot use the data directory: ")


def test_a_journal_failure_of_the_body_names_the_command_that_recovers(scan: ScanContext) -> None:
    err = io.StringIO()

    code = cli_journal.with_journal(scan, err, full, recover=RECOVER)

    assert code == 3
    assert err.getvalue() == (
        "safeclean: journal failed: database or disk is full; run 'safeclean thing recover'\n"
    )
