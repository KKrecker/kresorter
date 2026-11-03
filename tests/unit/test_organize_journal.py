"""Organize's journal (decision 0012, items 24, 25, 27 and 31): a batch and its moves, the
identity of a file, and what the disk says of a move.

A path holds *the file* of a move when it is a regular file with the journaled device, inode,
size and ``mtime_ns``: a rename keeps all four, a copy does not. Where a rename that raised left
a file is asked of the disk this way, by the mover as by recovery.
"""

import os
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from kresorter.organize.journal import (
    BatchState,
    Held,
    Identity,
    JournaledMove,
    MoveState,
    batch_state,
    begin,
    finish,
    holds,
    identity,
    journaled,
    set_move,
    settle,
)
from kresorter.storage.db import connect
from support.files import write
from support.host import MTIME_STEP_NS

FILE = b"the file"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    yield connection
    connection.close()


def batch_row(conn: sqlite3.Connection, batch: int) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT kind, folder, state, created_at_ns, finished_at_ns, error FROM move_batches"
        " WHERE id = ?",
        (batch,),
    ).fetchone()
    assert row is not None
    return tuple(row)


# --- a batch and its moves ----------------------------------------------------------------------


def test_a_batch_and_its_moves_are_journaled_pending_together(
    conn: sqlite3.Connection, zone: Path
) -> None:
    # [0012.24] [0012.25] one transaction: the batch, then every move, all pending
    a, b = write(zone / "a.jpg"), write(zone / "b.pdf")
    moves = [
        (a, zone / "Images" / "a.jpg", identity(a)),
        (b, zone / "Documents" / "b.pdf", identity(b)),
    ]
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    batch, ids = begin(conn, zone, moves, lambda: 7)
    conn.set_trace_callback(None)
    assert [s.split()[0] for s in statements] == ["BEGIN", "INSERT", "INSERT", "INSERT", "COMMIT"]
    assert batch_row(conn, batch) == ("organize", str(zone), "pending", 7, None, None)
    assert journaled(conn, batch) == [
        JournaledMove(ids[0], a, zone / "Images" / "a.jpg", identity(a), MoveState.PENDING),
        JournaledMove(ids[1], b, zone / "Documents" / "b.pdf", identity(b), MoveState.PENDING),
    ]


def test_a_move_and_a_batch_change_state(conn: sqlite3.Connection, zone: Path) -> None:
    # [0012.27]
    a = write(zone / "a.jpg")
    batch, (move,) = begin(conn, zone, [(a, zone / "Images" / "a.jpg", identity(a))], lambda: 1)
    set_move(conn, move, MoveState.DONE)
    finish(conn, batch, BatchState.FAILED, "it stopped", lambda: 9)
    assert [m.state for m in journaled(conn, batch)] == [MoveState.DONE]
    assert batch_row(conn, batch) == ("organize", str(zone), "failed", 1, 9, "it stopped")


def test_numbers_beyond_sqlite_integers_come_back_as_they_were(
    conn: sqlite3.Connection, zone: Path
) -> None:
    # [0012.24] device and inode numbers are unsigned 64-bit; SQLite keeps signed ones
    huge = Identity(device=2**64 - 1, inode=2**63, size=0, mtime_ns=-1)
    batch, _ = begin(conn, zone, [(zone / "a.jpg", zone / "Images" / "a.jpg", huge)], lambda: 1)
    assert [m.file for m in journaled(conn, batch)] == [huge]


@pytest.mark.parametrize(
    ("states", "outcome"),
    [
        ([MoveState.DONE, MoveState.DONE], BatchState.DONE),
        ([MoveState.ROLLED_BACK, MoveState.ROLLED_BACK], BatchState.ROLLED_BACK),
        ([MoveState.DONE, MoveState.ROLLED_BACK], BatchState.FAILED),
        ([MoveState.ROLLED_BACK, MoveState.FAILED], BatchState.FAILED),
    ],
)
def test_a_batch_is_done_or_rolled_back_only_when_every_move_is(
    states: list[MoveState], outcome: BatchState
) -> None:
    # [0012.27]
    assert batch_state(states) is outcome


# --- the identity of a file, and what a path holds ----------------------------------------------


def test_the_identity_of_a_file_is_its_device_inode_size_and_mtime(zone: Path) -> None:
    # [0012.31]
    info = write(zone / "a.jpg", FILE).lstat()
    assert identity(zone / "a.jpg") == Identity(
        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
    )


def test_a_rename_keeps_the_file(zone: Path) -> None:
    # [0012.31]
    file = identity(write(zone / "a.jpg", FILE))
    (zone / "a.jpg").rename(zone / "b.jpg")
    assert holds(zone / "b.jpg", file) is Held.THE_FILE


def test_a_hard_link_is_the_file_too(zone: Path) -> None:
    # [0012.31]
    file = identity(write(zone / "a.jpg", FILE))
    (zone / "b.jpg").hardlink_to(zone / "a.jpg")
    assert holds(zone / "b.jpg", file) is Held.THE_FILE


def test_a_copy_with_the_same_size_and_mtime_is_another_file(zone: Path) -> None:
    # [0012.31] as cp -p or a sync client restoring the file would make it
    file = identity(write(zone / "a.jpg", FILE))
    shutil.copy2(zone / "a.jpg", zone / "b.jpg")
    assert (zone / "b.jpg").lstat().st_mtime_ns == file.mtime_ns
    assert holds(zone / "b.jpg", file) is Held.ANOTHER_FILE


def test_the_file_edited_since_is_another_file(zone: Path) -> None:
    # [0012.31] the same inode, another mtime_ns
    file = identity(write(zone / "a.jpg", FILE))
    os.utime(zone / "a.jpg", ns=(file.mtime_ns, file.mtime_ns + MTIME_STEP_NS))
    assert holds(zone / "a.jpg", file) is Held.ANOTHER_FILE


def test_a_link_to_the_file_is_a_link(zone: Path) -> None:
    # [0012.31] never followed
    file = identity(write(zone / "a.jpg", FILE))
    (zone / "b.jpg").symlink_to(zone / "a.jpg")
    assert holds(zone / "b.jpg", file) is Held.LINK


def test_a_directory_and_nothing(zone: Path) -> None:
    # [0012.31]
    file = identity(write(zone / "a.jpg", FILE))
    (zone / "dir").mkdir()
    assert holds(zone / "dir", file) is Held.DIRECTORY
    assert holds(zone / "missing", file) is Held.NOTHING


def test_what_a_path_holds_is_named_as_warnings_name_it() -> None:
    # [0012.31]
    assert [h.value for h in Held] == [
        "nothing",
        "another file",
        "a link",
        "a directory",
        "the file",
    ]


# --- a move settled by the disk (the table of item 31) ------------------------------------------


def place(zone: Path, at_source: Held, at_destination: Held) -> tuple[Path, Path, Identity]:
    """A move from zone/a.jpg to zone/Images/a.jpg whose paths hold what each test says."""
    source, destination = zone / "a.jpg", zone / "Images" / "a.jpg"
    original = write(zone / "original.jpg", FILE)
    file = identity(original)
    for path, held in ((source, at_source), (destination, at_destination)):
        path.parent.mkdir(exist_ok=True)
        if held is Held.THE_FILE:
            path.hardlink_to(original)
        elif held is Held.ANOTHER_FILE:
            write(path, b"another")
        elif held is Held.LINK:
            path.symlink_to(original)
        elif held is Held.DIRECTORY:
            path.mkdir()
    return source, destination, file


OTHERS = [Held.NOTHING, Held.ANOTHER_FILE, Held.LINK, Held.DIRECTORY]


@pytest.mark.parametrize("at_source", OTHERS)
def test_the_file_at_its_destination_only_is_done(zone: Path, at_source: Held) -> None:
    # [0012.27] [0012.31]
    assert settle(*place(zone, at_source, Held.THE_FILE)) == (MoveState.DONE, None)


@pytest.mark.parametrize("at_destination", OTHERS)
def test_the_file_at_its_source_only_is_rolled_back(zone: Path, at_destination: Held) -> None:
    # [0012.27] [0012.31]
    assert settle(*place(zone, Held.THE_FILE, at_destination)) == (MoveState.ROLLED_BACK, None)


def test_the_file_at_both_paths_is_failed(zone: Path) -> None:
    # [0012.31] two hard links: neither path is taken from the other
    source, destination, file = place(zone, Held.THE_FILE, Held.THE_FILE)
    assert settle(source, destination, file) == (
        MoveState.FAILED,
        f"FAILED: {source} -> {destination}: at the source the file,"
        " at the destination the file; neither was touched",
    )


@pytest.mark.parametrize("at_source", OTHERS)
@pytest.mark.parametrize("at_destination", OTHERS)
def test_the_file_at_neither_path_is_failed_and_both_are_named(
    zone: Path, at_source: Held, at_destination: Held
) -> None:
    # [0012.31]
    source, destination, file = place(zone, at_source, at_destination)
    assert settle(source, destination, file) == (
        MoveState.FAILED,
        f"FAILED: {source} -> {destination}: at the source {at_source},"
        f" at the destination {at_destination}; neither was touched",
    )
