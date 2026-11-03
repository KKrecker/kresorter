"""Recovery of interrupted organize batches, by the disk (decision 0012, item 31).

A crash is a child process that exits (``os._exit``) at the rename a test chooses, or, for a
recovery, at the statement to the journal it chooses, so nothing after it runs: the journal and
the disk are what a real crash leaves (item 40). Recovery moves nothing, so ``tree`` is the same
before and after it; afterwards ``where`` (the journal) says exactly where each file is.
"""

import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path

import pytest

from kresorter.organize.journal import BatchState
from kresorter.organize.mover import carry_out
from kresorter.organize.recovery import RecoveredBatch, RecoveryReport, recover
from kresorter.storage.db import connect
from support.files import write
from support.moves import (
    MOVED,
    SOURCES,
    A,
    B,
    C,
    Fault,
    Interrupt,
    batches,
    content,
    copy_journal,
    crash,
    crash_recovery,
    files,
    planned,
    recovery_statements,
    three_files,
    tree,
    where,
)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    yield connection
    connection.close()


@pytest.fixture
def folder(zone: Path) -> Path:
    return three_files(zone)


def crashed(tmp_path: Path, folder: Path, faults: dict[Path, Fault]) -> None:
    crash(tmp_path / "journal.db", folder, planned(folder), faults)


def failed(source: Path, destination: Path, at_source: str, at_destination: str) -> str:
    return (
        f"FAILED: {source} -> {destination}: at the source {at_source},"
        f" at the destination {at_destination}; neither was touched"
    )


# --- crashes during the batch -------------------------------------------------------------------


def test_a_crash_right_after_a_rename_is_settled_done(
    conn: sqlite3.Connection, tmp_path: Path, zone: Path, folder: Path
) -> None:
    # [0012.31] [0012.40] b moved, its done never written: the disk says done; a real exit
    crashed(tmp_path, folder, {folder / B: "exit-after"})
    before = tree(zone)
    report = recover(conn)
    expected = {A: MOVED[A], B: MOVED[B], C: C}
    assert where(conn, folder) == expected
    assert files(folder) == content(expected)
    assert tree(zone) == before
    assert batches(conn) == ["failed"]
    assert report.warnings == ()


def test_a_crash_right_before_a_rename_is_settled_rolled_back(
    conn: sqlite3.Connection, tmp_path: Path, zone: Path, folder: Path
) -> None:
    # [0012.31] b never left its source
    crashed(tmp_path, folder, {folder / B: "exit-before"})
    before = tree(zone)
    recover(conn)
    expected = {A: MOVED[A], B: B, C: C}
    assert where(conn, folder) == expected
    assert files(folder) == content(expected)
    assert tree(zone) == before
    assert batches(conn) == ["failed"]


# --- crashes during the rollback ----------------------------------------------------------------


def test_a_rollback_crashed_right_after_a_move_back(
    conn: sqlite3.Connection, tmp_path: Path, zone: Path, folder: Path
) -> None:
    # [0012.27] [0012.31] c failed, b went back, a went back and the crash came before its
    # rolled_back was written: the journal says done, the disk says otherwise, the disk wins
    crashed(tmp_path, folder, {folder / C: "before", folder / MOVED[A]: "exit-after"})
    assert where(conn, folder) == {A: MOVED[A], B: B, C: C}
    before = tree(zone)
    recover(conn)
    assert where(conn, folder) == SOURCES
    assert files(folder) == content(SOURCES)
    assert tree(zone) == before
    assert batches(conn) == ["rolled_back"]


def test_a_rollback_crashed_right_before_a_move_back(
    conn: sqlite3.Connection, tmp_path: Path, zone: Path, folder: Path
) -> None:
    # [0012.27] [0012.31] a never went back: it stays sorted, done, for undo
    crashed(tmp_path, folder, {folder / C: "before", folder / MOVED[A]: "exit-before"})
    before = tree(zone)
    report = recover(conn)
    expected = {A: MOVED[A], B: B, C: C}
    assert where(conn, folder) == expected
    assert files(folder) == content(expected)
    assert tree(zone) == before
    assert batches(conn) == ["failed"]
    assert report.done == (folder / A,)


def test_an_interrupted_recovery_settles_the_same_when_run_again(
    conn: sqlite3.Connection, tmp_path: Path, zone: Path, folder: Path
) -> None:
    # [0012.31] interrupted after settling the moves, before closing the batch (its clock)
    crashed(tmp_path, folder, {folder / B: "exit-after"})
    before = tree(zone)

    def interrupted() -> int:
        raise Interrupt

    with pytest.raises(Interrupt):
        recover(conn, now=interrupted)
    assert batches(conn) == ["pending"]
    recover(conn)
    assert where(conn, folder) == {A: MOVED[A], B: MOVED[B], C: C}
    assert tree(zone) == before
    assert batches(conn) == ["failed"]


def test_a_recovery_crashed_at_any_statement_settles_the_same_when_run_again(
    tmp_path: Path, zone: Path, folder: Path
) -> None:
    # [0012.31] each move is settled in a transaction of its own and the batch is closed last:
    # wherever a recovery crashes, the next one finds the batch pending and settles every move
    crashed(tmp_path, folder, {folder / B: "exit-after"})
    journal = tmp_path / "journal.db"
    before = tree(zone)
    sent = recovery_statements(copy_journal(journal, tmp_path / "counted.db"))
    settled = []
    for statement in range(1, sent + 1):
        copy = copy_journal(journal, tmp_path / f"crashed-at-{statement}.db")
        crash_recovery(copy, statement)
        with closing(connect(copy)) as conn:
            recover(conn)
            settled.append((where(conn, folder), batches(conn)))
    expected = ({A: MOVED[A], B: MOVED[B], C: C}, ["failed"])
    assert sent > 1
    assert settled == [expected] * sent
    assert tree(zone) == before


# --- what recovery reports ----------------------------------------------------------------------


def test_nothing_pending_is_nothing_to_recover(conn: sqlite3.Connection, folder: Path) -> None:
    # [0012.31] a finished batch is not touched, and nothing is written
    carry_out(conn, folder, planned(folder))
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    assert recover(conn) == RecoveryReport()
    conn.set_trace_callback(None)
    assert [s.split()[0] for s in statements] == ["SELECT"]
    assert batches(conn) == ["done"]


def test_the_report_names_every_batch_and_the_files_still_sorted(
    conn: sqlite3.Connection, tmp_path: Path, folder: Path
) -> None:
    # [0012.31] by source, by what each move became, and by batch with its destinations left
    crashed(tmp_path, folder, {folder / B: "exit-after"})
    assert recover(conn) == RecoveryReport(
        done=(folder / A, folder / B),
        rolled_back=(folder / C,),
        batches=(RecoveredBatch(1, BatchState.FAILED, (folder / MOVED[A], folder / MOVED[B])),),
    )


def test_a_batch_every_move_of_which_is_done_closes_done(
    conn: sqlite3.Connection, tmp_path: Path, folder: Path
) -> None:
    # [0012.31] the crash came after the last rename: recovery completes nothing, it says so
    crashed(tmp_path, folder, {folder / C: "exit-after"})
    report = recover(conn)
    assert report.batches == (
        RecoveredBatch(1, BatchState.DONE, tuple(folder / MOVED[n] for n in (A, B, C))),
    )
    assert where(conn, folder) == MOVED


def test_a_batch_every_move_of_which_is_rolled_back_closes_rolled_back(
    conn: sqlite3.Connection, tmp_path: Path, folder: Path
) -> None:
    # [0012.31]
    crashed(tmp_path, folder, {folder / A: "exit-before"})
    assert recover(conn).batches == (RecoveredBatch(1, BatchState.ROLLED_BACK, ()),)


def test_every_pending_batch_is_recovered_oldest_first(
    conn: sqlite3.Connection, tmp_path: Path, zone: Path, folder: Path
) -> None:
    # [0012.31]
    crashed(tmp_path, folder, {folder / A: "exit-before"})
    desktop = zone / "Desktop"
    write(desktop / "d.png", b"d.png")
    crash(
        tmp_path / "journal.db",
        desktop,
        [(desktop / "d.png", desktop / "Images" / "d.png")],
        {desktop / "d.png": "exit-after"},
    )
    report = recover(conn)
    assert report.batches == (
        RecoveredBatch(1, BatchState.ROLLED_BACK, ()),
        RecoveredBatch(2, BatchState.DONE, (desktop / "Images" / "d.png",)),
    )
    assert batches(conn) == ["rolled_back", "done"]


def test_a_recovered_batch_says_it_was_interrupted(
    conn: sqlite3.Connection, tmp_path: Path, folder: Path
) -> None:
    # [0012.31] closed when recovery closed it
    crashed(tmp_path, folder, {folder / A: "exit-before"})
    recover(conn, now=lambda: 42)
    assert conn.execute("SELECT finished_at_ns, error FROM move_batches").fetchall() == [
        (42, "interrupted; settled by recovery")
    ]


# --- the file's identity ------------------------------------------------------------------------


@pytest.mark.parametrize("number", ["device", "inode"])
def test_a_number_changed_by_a_remount_fails_the_move(
    number: str, conn: sqlite3.Connection, tmp_path: Path, zone: Path, folder: Path
) -> None:
    # [0012.31] after a remount the disk numbers a's file anew: recovery cannot tell it is a
    crashed(tmp_path, folder, {folder / B: "exit-after"})
    conn.execute(f"UPDATE moves SET {number} = {number} + 1 WHERE source = ?", (str(folder / A),))
    before = tree(zone)
    report = recover(conn)
    assert where(conn, folder) == {A: "failed", B: MOVED[B], C: C}
    assert report.warnings == (failed(folder / A, folder / MOVED[A], "nothing", "another file"),)
    assert tree(zone) == before


def theirs(path: Path) -> None:
    write(path, b"theirs")


def two_other_files(source: Path, destination: Path, zone: Path) -> None:
    theirs(source)
    destination.write_bytes(b"edited since: the same inode, another size")


def both_empty(source: Path, destination: Path, zone: Path) -> None:
    destination.rename(zone / "kept.jpg")  # the user put a elsewhere


def a_link_and_a_directory(source: Path, destination: Path, zone: Path) -> None:
    destination.rename(zone / "kept.jpg")
    source.symlink_to(zone / "kept.jpg")
    destination.mkdir()


@pytest.mark.parametrize(
    ("meanwhile", "said"),
    [
        (two_other_files, ("another file", "another file")),
        (both_empty, ("nothing", "nothing")),
        (a_link_and_a_directory, ("a link", "a directory")),
    ],
    ids=["two-other-files", "both-empty", "a-link-and-a-directory"],
)
def test_both_paths_taken_by_something_else_are_left_alone(
    meanwhile: Callable[[Path, Path, Path], None],
    said: tuple[str, str],
    conn: sqlite3.Connection,
    tmp_path: Path,
    zone: Path,
    folder: Path,
) -> None:
    # [0012.31] a moved and the crash came; then, before recovery, someone else was at work
    crashed(tmp_path, folder, {folder / A: "exit-after"})
    meanwhile(folder / A, folder / MOVED[A], zone)
    before = tree(zone)
    report = recover(conn)
    assert where(conn, folder) == {A: "failed", B: B, C: C}
    assert report.failed == (folder / A,)
    assert report.warnings == (failed(folder / A, folder / MOVED[A], *said),)
    assert tree(zone) == before


def test_the_file_at_both_paths_is_left_alone(
    conn: sqlite3.Connection, tmp_path: Path, zone: Path, folder: Path
) -> None:
    # [0012.31] two hard links to a's file: recovery does not choose
    crashed(tmp_path, folder, {folder / A: "exit-after"})
    os.link(folder / MOVED[A], folder / A)
    before = tree(zone)
    report = recover(conn)
    assert where(conn, folder)[A] == "failed"
    assert report.warnings == (failed(folder / A, folder / MOVED[A], "the file", "the file"),)
    assert tree(zone) == before


def test_the_file_at_its_destination_and_theirs_at_its_source_is_done(
    conn: sqlite3.Connection, tmp_path: Path, zone: Path, folder: Path
) -> None:
    # [0012.31] the first row of the table: the newcomer at the source is not a
    crashed(tmp_path, folder, {folder / A: "exit-after"})
    theirs(folder / A)
    before = tree(zone)
    recover(conn)
    expected = {A: MOVED[A], B: B, C: C}
    assert where(conn, folder) == expected
    assert files(folder) == {**content(expected), A: b"theirs"}
    assert tree(zone) == before


def test_the_file_at_its_source_and_theirs_at_its_destination_is_rolled_back(
    conn: sqlite3.Connection, tmp_path: Path, zone: Path, folder: Path
) -> None:
    # [0012.31] the second row: what appeared at the destination is not a
    crashed(tmp_path, folder, {folder / A: "exit-before"})
    theirs(folder / MOVED[A])
    before = tree(zone)
    recover(conn)
    assert where(conn, folder) == SOURCES
    assert files(folder) == {**content(SOURCES), MOVED[A]: b"theirs"}
    assert tree(zone) == before
