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

from safeclean import cli_journal
from safeclean.core.scanner import ScanContext
from safeclean.storage.pending import Domain

RECOVER = "safeclean thing recover"  # the domain's own command, passed in by it


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


@pytest.mark.parametrize(
    ("domains", "work"),
    [
        ({Domain.QUARANTINE}, "quarantine"),
        ({Domain.QUARANTINE, Domain.AUTOSTART}, "autostart and quarantine"),
    ],
    ids=["one", "two"],
)
def test_work_of_other_domains_names_the_one_recover_command(
    domains: set[Domain], work: str
) -> None:
    assert cli_journal.unfinished(domains) == (
        f"safeclean: the journal has unfinished {work} work; run 'safeclean recover' first;"
        " nothing was changed\n"
    )
