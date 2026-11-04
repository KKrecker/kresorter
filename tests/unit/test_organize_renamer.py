"""Organize's renames on Windows, tried again while a handle refuses them (decision 0017, items
3 and 4).

Windows raises ``PermissionError`` while another program holds the file without sharing
deletion (a sharing or lock violation, or access denied while an antivirus looks at it).
``HeldRename`` raises it for the first renames of a path; ``Sleeps`` records the waits instead
of taking them. Three files, one per category, each holding its own name (``support.moves``).
"""

import inspect
import os
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from kresorter.organize.mover import BatchState, Rename, carry_out
from kresorter.organize.platforms import renamer
from kresorter.storage.db import connect
from support.moves import (
    MOVED,
    SOURCES,
    A,
    B,
    C,
    HeldRename,
    Sleeps,
    batches,
    content,
    files,
    planned,
    three_files,
    where,
)

DELAYS = [0.1, 0.2, 0.4, 0.8, 1.6]


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    yield connection
    connection.close()


@pytest.fixture
def folder(zone: Path) -> Path:
    return three_files(zone)


@pytest.fixture
def sleeps() -> Sleeps:
    return Sleeps()


def windows(rename: Rename, sleeps: Sleeps) -> Rename:
    return renamer("windows", rename=rename, sleep=sleeps)


# --- the rename ---------------------------------------------------------------------------------


def test_linux_and_macos_rename_once() -> None:
    # [0017.3] os.rename itself, no wait
    assert renamer("linux") is os.rename
    assert renamer("darwin") is os.rename


def test_a_held_file_on_linux_fails_at_the_first_try(folder: Path, sleeps: Sleeps) -> None:
    # [0017.3]
    held = HeldRename({folder / A: 1})
    with pytest.raises(PermissionError):
        renamer("linux", rename=held, sleep=sleeps)(folder / A, folder / "moved.jpg")
    assert (len(held.calls), sleeps.delays) == (1, [])


def test_windows_tries_again_until_the_handle_is_gone(folder: Path, sleeps: Sleeps) -> None:
    # [0017.3] two refusals, then the move
    held = HeldRename({folder / A: 2})
    windows(held, sleeps)(folder / A, folder / "moved.jpg")
    assert (folder / "moved.jpg").read_bytes() == b"a.jpg"
    assert (len(held.calls), sleeps.delays) == (3, [0.1, 0.2])


def test_windows_tries_six_times_in_about_three_seconds(folder: Path, sleeps: Sleeps) -> None:
    # [0017.3] the sixth refusal is the rename's error
    held = HeldRename({folder / A: 6})
    with pytest.raises(PermissionError, match="used by another process"):
        windows(held, sleeps)(folder / A, folder / "moved.jpg")
    assert (len(held.calls), sleeps.delays) == (6, DELAYS)
    assert sum(sleeps.delays) == pytest.approx(3.1)
    assert (folder / A).read_bytes() == b"a.jpg"


def test_windows_raises_any_other_error_at_once(folder: Path, sleeps: Sleeps) -> None:
    # [0017.3] a missing source, a destination under a file: no wait
    held = HeldRename({})
    with pytest.raises(FileNotFoundError):
        windows(held, sleeps)(folder / "missing.jpg", folder / "moved.jpg")
    with pytest.raises(OSError, match=r"^\[(Errno 20|WinError 87)\] "):  # not a directory
        windows(held, sleeps)(folder / A, folder / B / "moved.jpg")
    assert (len(held.calls), sleeps.delays) == (2, [])


def test_the_waits_are_real_by_default() -> None:
    # [0017.3]
    parameters = inspect.signature(renamer).parameters
    assert parameters["rename"].default is os.rename
    assert parameters["sleep"].default is time.sleep


# --- what keeps failing (0012 item 27) ----------------------------------------------------------


def test_a_move_held_through_every_try_stops_and_rolls_back(
    conn: sqlite3.Connection, folder: Path, sleeps: Sleeps
) -> None:
    # [0017.4] b is held six times: c is never tried, a goes back at its first try
    held = HeldRename({folder / B: 6})
    result = carry_out(conn, folder, planned(folder), rename=windows(held, sleeps))
    assert (result.state, result.left) == (BatchState.ROLLED_BACK, ())
    assert held.calls == [
        (folder / A, folder / MOVED[A]),
        *[(folder / B, folder / MOVED[B])] * 6,
        (folder / MOVED[A], folder / A),
    ]
    assert sleeps.delays == DELAYS
    assert where(conn, folder) == SOURCES
    assert files(folder) == content(SOURCES)


def test_a_move_back_gets_the_same_tries(
    conn: sqlite3.Connection, folder: Path, sleeps: Sleeps
) -> None:
    # [0017.4] a, held twice on its way back, goes back at the third try
    held = HeldRename({folder / B: 6, folder / MOVED[A]: 2})
    result = carry_out(conn, folder, planned(folder), rename=windows(held, sleeps))
    assert (result.state, result.left) == (BatchState.ROLLED_BACK, ())
    assert sleeps.delays == [*DELAYS, 0.1, 0.2]
    assert files(folder) == content(SOURCES)


def test_a_move_back_held_through_every_try_leaves_its_file_done(
    conn: sqlite3.Connection, folder: Path, sleeps: Sleeps
) -> None:
    # [0017.4] b stays at its destination, its move done, the batch failed; a still goes back
    held = HeldRename({folder / C: 6, folder / MOVED[B]: 6})
    result = carry_out(conn, folder, planned(folder), rename=windows(held, sleeps))
    assert (result.state, result.left) == (BatchState.FAILED, (folder / MOVED[B],))
    assert sleeps.delays == [*DELAYS, *DELAYS]
    expected = {A: A, B: MOVED[B], C: C}
    assert where(conn, folder) == expected
    assert files(folder) == content(expected)
    assert batches(conn) == ["failed"]
