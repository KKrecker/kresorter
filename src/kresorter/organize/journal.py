"""Organize's journal (decision 0012, items 24, 25, 27, 29 and 31): batches and their moves in
the ``move_batches`` and ``moves`` tables, and what the disk says of a move. An undo is a batch
of kind ``undo`` whose moves name, in ``undoes``, the moves they reverse.

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

from kresorter.storage.journal import Clock, insert_row
from kresorter.storage.transactions import transaction

__all__ = [
    "Batch",
    "BatchKind",
    "BatchState",
    "Held",
    "Identity",
    "JournaledMove",
    "MoveState",
    "Summary",
    "batch",
    "batch_state",
    "begin",
    "finish",
    "holds",
    "identity",
    "journaled",
    "pending_batches",
    "set_move",
    "set_moves",
    "settle",
    "summaries",
    "undoable",
]

_BIT_64 = 1 << 64
_BIT_63 = 1 << 63


class BatchKind(StrEnum):
    ORGANIZE = "organize"
    UNDO = "undo"  # its moves name the moves they reverse


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
class Batch:
    batch_id: int
    kind: BatchKind
    folder: Path
    state: BatchState
    created_at_ns: int
    undoing: int | None  # the batch an undo batch reverses


@dataclass(frozen=True)
class Summary:
    """A batch as ``organize list`` shows it."""

    batch: Batch
    moved: int  # its done moves
    undone: int  # of those, the ones a done move undoes


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
    undoes: Sequence[int] | None = None,
) -> tuple[int, list[int]]:
    """Journal a batch and every move ``pending``, in one transaction: its id and theirs. With
    ``undoes``, the batch is an undo and each move names the move it reverses."""
    kind = BatchKind.ORGANIZE if undoes is None else BatchKind.UNDO
    reversed_moves = [None] * len(moves) if undoes is None else list(undoes)
    with transaction(conn):
        batch = insert_row(
            conn,
            "INSERT INTO move_batches (kind, folder, state, created_at_ns) VALUES (?, ?, ?, ?)",
            (kind, str(folder), BatchState.PENDING, now()),
        )
        ids = [
            insert_row(
                conn,
                "INSERT INTO moves (batch_id, source, destination, device, inode, size,"
                " mtime_ns, state, undoes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch,
                    str(source),
                    str(destination),
                    _signed(file.device),
                    _signed(file.inode),
                    file.size,
                    file.mtime_ns,
                    MoveState.PENDING,
                    undone,
                ),
            )
            for (source, destination, file), undone in zip(moves, reversed_moves, strict=True)
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


def batch(conn: sqlite3.Connection, batch_id: int) -> Batch | None:
    """The batch ``batch_id`` as the journal keeps it, or None."""
    found = _batches(conn, "id = ?", (batch_id,))
    return found[0] if found else None


def pending_batches(conn: sqlite3.Connection) -> list[Batch]:
    """The batches still ``pending``, oldest first."""
    return _batches(conn, "state = ?", (BatchState.PENDING,))


def summaries(conn: sqlite3.Connection) -> list[Summary]:
    """Every batch, newest first, with its done moves and how many of them are undone."""
    counts = {
        batch_id: (moved, undone)
        for batch_id, moved, undone in conn.execute(
            "SELECT m.batch_id, COUNT(*), COUNT(u.id) FROM moves m LEFT JOIN moves u"
            " ON u.undoes = m.id AND u.state = ? WHERE m.state = ? GROUP BY m.batch_id",
            (MoveState.DONE, MoveState.DONE),
        )
    }
    return [
        Summary(found, *counts.get(found.batch_id, (0, 0)))
        for found in reversed(_batches(conn, "1", ()))
    ]


def _batches(conn: sqlite3.Connection, where: str, parameters: tuple[object, ...]) -> list[Batch]:
    rows = conn.execute(
        "SELECT id, kind, folder, state, created_at_ns, (SELECT o.batch_id FROM moves u"
        " JOIN moves o ON o.id = u.undoes WHERE u.batch_id = b.id LIMIT 1)"
        f" FROM move_batches b WHERE {where} ORDER BY id",
        parameters,
    )
    return [
        Batch(batch_id, BatchKind(kind), Path(folder), BatchState(state), created, undoing)
        for batch_id, kind, folder, state, created, undoing in rows
    ]


def journaled(conn: sqlite3.Connection, batch: int) -> list[JournaledMove]:
    """The moves of ``batch``, in the order they were journaled."""
    return _moves(
        conn,
        "SELECT id, source, destination, device, inode, size, mtime_ns, state FROM moves"
        " WHERE batch_id = ? ORDER BY id",
        batch,
    )


def undoable(conn: sqlite3.Connection, batch: int) -> list[JournaledMove]:
    """The ``done`` moves of ``batch`` that no ``done`` move undoes yet, in journal order."""
    return _moves(
        conn,
        "SELECT id, source, destination, device, inode, size, mtime_ns, state FROM moves m"
        " WHERE batch_id = ? AND state = 'done' AND NOT EXISTS"
        " (SELECT 1 FROM moves u WHERE u.undoes = m.id AND u.state = 'done') ORDER BY id",
        batch,
    )


def _moves(conn: sqlite3.Connection, query: str, batch: int) -> list[JournaledMove]:
    rows = conn.execute(query, (batch,))
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
