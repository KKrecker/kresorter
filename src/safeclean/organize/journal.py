"""Organize's journal (decision 0012, items 24, 25, 27 and 31): batches and their moves in the
``move_batches`` and ``moves`` tables, and what the disk says of a move.

A path holds *the file* of a move when it is a regular file with the journaled device, inode,
size and ``mtime_ns``: a rename keeps all four; a copy, a newcomer, a save by replacement, the
file edited since or a remount that renumbered it does not. ``settle`` asks the disk where a
move left its file, for the mover after a rename that raised as for recovery.

Device and inode numbers are unsigned 64-bit, SQLite integers signed: they are kept in two's
complement and read back as they were.
"""

from __future__ import annotations

import sqlite3
import stat
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from safeclean.storage.journal import Clock, insert_row
from safeclean.storage.transactions import transaction

__all__ = [
    "BatchState",
    "Held",
    "Identity",
    "JournaledMove",
    "MoveState",
    "batch_state",
    "begin",
    "finish",
    "holds",
    "identity",
    "journaled",
    "set_move",
    "set_moves",
    "settle",
]

_BIT_64 = 1 << 64
_BIT_63 = 1 << 63


class BatchState(StrEnum):
    PENDING = "pending"
    DONE = "done"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class MoveState(StrEnum):
    PENDING = "pending"
    DONE = "done"  # the file is at the destination
    ROLLED_BACK = "rolled_back"  # the file is at the source
    FAILED = "failed"  # neither, or both: the user decides


class Held(StrEnum):
    """What a path holds, as warnings name it."""

    NOTHING = "nothing"
    ANOTHER_FILE = "another file"
    LINK = "a link"
    DIRECTORY = "a directory"
    THE_FILE = "the file"


@dataclass(frozen=True)
class Identity:
    device: int
    inode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class JournaledMove:
    move_id: int
    source: Path
    destination: Path
    file: Identity
    state: MoveState


def identity(path: Path) -> Identity:
    """The identity of the file at ``path``, as ``lstat`` sees it."""
    info = path.lstat()
    return Identity(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def holds(path: Path, file: Identity) -> Held:
    """What ``path`` holds, compared with ``file``; links are never followed."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return Held.NOTHING
    if stat.S_ISLNK(info.st_mode):
        return Held.LINK
    if stat.S_ISDIR(info.st_mode):
        return Held.DIRECTORY
    found = Identity(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    return Held.THE_FILE if stat.S_ISREG(info.st_mode) and found == file else Held.ANOTHER_FILE


def settle(source: Path, destination: Path, file: Identity) -> tuple[MoveState, str | None]:
    """Where the disk says the file of a move is, and the warning of a ``failed`` move."""
    at_source, at_destination = holds(source, file), holds(destination, file)
    if at_destination is Held.THE_FILE and at_source is not Held.THE_FILE:
        return MoveState.DONE, None
    if at_source is Held.THE_FILE and at_destination is not Held.THE_FILE:
        return MoveState.ROLLED_BACK, None
    return MoveState.FAILED, (
        f"FAILED: {source} -> {destination}: at the source {at_source},"
        f" at the destination {at_destination}; neither was touched"
    )


def begin(
    conn: sqlite3.Connection,
    folder: Path,
    moves: Sequence[tuple[Path, Path, Identity]],
    now: Clock,
) -> tuple[int, list[int]]:
    """Journal a batch and every move ``pending``, in one transaction: its id and theirs."""
    with transaction(conn):
        batch = insert_row(
            conn,
            "INSERT INTO move_batches (kind, folder, state, created_at_ns) VALUES (?, ?, ?, ?)",
            ("organize", str(folder), BatchState.PENDING, now()),
        )
        ids = [
            insert_row(
                conn,
                "INSERT INTO moves (batch_id, source, destination, device, inode, size,"
                " mtime_ns, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch,
                    str(source),
                    str(destination),
                    _signed(file.device),
                    _signed(file.inode),
                    file.size,
                    file.mtime_ns,
                    MoveState.PENDING,
                ),
            )
            for source, destination, file in moves
        ]
    return batch, ids


def set_move(conn: sqlite3.Connection, move_id: int, state: MoveState) -> None:
    set_moves(conn, [move_id], state)


def set_moves(conn: sqlite3.Connection, move_ids: Iterable[int], state: MoveState) -> None:
    """Every move of ``move_ids`` takes ``state``, in one transaction."""
    with transaction(conn):
        conn.executemany(
            "UPDATE moves SET state = ? WHERE id = ?", [(state, move) for move in move_ids]
        )


def finish(
    conn: sqlite3.Connection, batch: int, state: BatchState, error: str | None, now: Clock
) -> None:
    finished = now()
    with transaction(conn):
        conn.execute(
            "UPDATE move_batches SET state = ?, error = ?, finished_at_ns = ? WHERE id = ?",
            (state, error, finished, batch),
        )


def journaled(conn: sqlite3.Connection, batch: int) -> list[JournaledMove]:
    """The moves of ``batch``, in the order they were journaled."""
    rows = conn.execute(
        "SELECT id, source, destination, device, inode, size, mtime_ns, state FROM moves"
        " WHERE batch_id = ? ORDER BY id",
        (batch,),
    )
    return [
        JournaledMove(
            move_id,
            Path(source),
            Path(destination),
            Identity(_unsigned(device), _unsigned(inode), size, mtime_ns),
            MoveState(state),
        )
        for move_id, source, destination, device, inode, size, mtime_ns, state in rows
    ]


def batch_state(states: Iterable[MoveState]) -> BatchState:
    """``done`` when every move is, ``rolled_back`` likewise, ``failed`` otherwise."""
    found = set(states)
    if found == {MoveState.DONE}:
        return BatchState.DONE
    if found == {MoveState.ROLLED_BACK}:
        return BatchState.ROLLED_BACK
    return BatchState.FAILED


def _signed(number: int) -> int:
    return number - _BIT_64 if number >= _BIT_63 else number


def _unsigned(number: int) -> int:
    return number + _BIT_64 if number < 0 else number
