"""Undo (decision 0012, items 4, 29 and 30): a batch of its own, kind ``undo``, whose moves name
the moves they reverse; only ``done`` moves not undone yet are taken.

What is at a destination goes back if it is a regular file, even changed since the move; a
missing file, a link or a directory stays, and a taken source is never overwritten. Preflight
and the mover are the batch's (``test_organize_mover.py``); here they run on undo plans.
"""

import dataclasses
import os
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, deny_stat
from kresorter.core.scanner import ScanContext
from kresorter.organize.journal import (
    Batch,
    BatchKind,
    BatchState,
    batch,
    begin,
    identity,
    journaled,
)
from kresorter.organize.mover import BatchResult, carry_out, check
from kresorter.organize.planner import Stay, StayReason
from kresorter.organize.recovery import RecoveredBatch, recover
from kresorter.organize.undo import UndoMove, UndoPlan, UndoReason, UndoRefused, plan_undo
from kresorter.storage.db import connect
from support.files import write
from support.moves import (
    MOVED,
    SOURCES,
    A,
    B,
    C,
    FlakyRename,
    batches,
    content,
    crash,
    files,
    planned,
    three_files,
    tree,
)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    yield connection
    connection.close()


@pytest.fixture
def folder(zone: Path) -> Path:
    return three_files(zone)


def sorted_out(conn: sqlite3.Connection, folder: Path) -> BatchResult:
    """The three files of ``folder`` sorted by batch 1."""
    result = carry_out(conn, folder, planned(folder))
    assert result.state is BatchState.DONE
    return result


def undo(
    conn: sqlite3.Connection,
    undo_plan: UndoPlan,
    rename: Callable[[Path, Path], None] = os.rename,
) -> BatchResult:
    """Carry ``undo_plan`` out as it stands, as ``organize undo --yes`` would after preflight."""
    moves = [(move.source, move.destination) for move in undo_plan.moves]
    undoes = [move.undoes for move in undo_plan.moves]
    return carry_out(conn, undo_plan.folder, moves, rename=rename, undoes=undoes)


def names(undo_plan: UndoPlan) -> list[str]:
    return [move.destination.name for move in undo_plan.moves]


# --- a batch of its own (item 29) ---------------------------------------------------------------


def test_undo_moves_back_what_the_batch_moved(conn: sqlite3.Connection, folder: Path) -> None:
    # [0012.29] from where each file is now to where it was, naming the move it reverses
    sorted_out(conn, folder)
    sorted_moves = journaled(conn, 1)
    undo_plan = plan_undo(conn, 1)
    assert undo_plan == UndoPlan(
        1,
        folder,
        tuple(
            UndoMove(
                move.destination,
                move.source,
                move.file.size,
                move.file.mtime_ns,
                undoes=move.move_id,
            )
            for move in sorted_moves
        ),
        (),
    )
    result = undo(conn, undo_plan)
    assert (result.batch_id, result.state) == (2, BatchState.DONE)
    assert files(folder) == content(SOURCES)
    assert batches(conn) == ["done", "done"]
    assert conn.execute("SELECT kind FROM move_batches ORDER BY id").fetchall() == [
        ("organize",),
        ("undo",),
    ]
    assert conn.execute("SELECT undoes FROM moves WHERE batch_id = 2 ORDER BY id").fetchall() == [
        (move.move_id,) for move in sorted_moves
    ]


def test_undo_leaves_the_category_directories(conn: sqlite3.Connection, folder: Path) -> None:
    # [0012.4] [0012.29] empty ones included: organize has no deletion point
    sorted_out(conn, folder)
    undo(conn, plan_undo(conn, 1))
    assert tree(folder) == {
        **content(SOURCES),
        "Audio": "dir",
        "Documents": "dir",
        "Images": "dir",
    }


def test_a_batch_is_described_as_the_journal_keeps_it(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.29] an undo batch names the batch it undoes
    sorted_out(conn, folder)
    undo(conn, plan_undo(conn, 1))
    created = [row[0] for row in conn.execute("SELECT created_at_ns FROM move_batches")]
    assert batch(conn, 1) == Batch(
        1, BatchKind.ORGANIZE, folder, BatchState.DONE, created[0], undoing=None
    )
    assert batch(conn, 2) == Batch(
        2, BatchKind.UNDO, folder, BatchState.DONE, created[1], undoing=1
    )
    assert batch(conn, 3) is None


def test_only_done_moves_are_taken(conn: sqlite3.Connection, folder: Path) -> None:
    # [0012.29] the batch stopped and b could not go back: b only is still sorted
    rename = FlakyRename({folder / C: "before", folder / MOVED[B]: "before"})
    assert carry_out(conn, folder, planned(folder), rename=rename).state is BatchState.FAILED
    undo_plan = plan_undo(conn, 1)
    assert (names(undo_plan), undo_plan.stays) == ([B], ())


def test_a_rolled_back_batch_has_nothing_to_undo(conn: sqlite3.Connection, folder: Path) -> None:
    # [0012.29]
    carry_out(conn, folder, planned(folder), rename=FlakyRename({folder / A: "before"}))
    assert plan_undo(conn, 1) == UndoPlan(1, folder, (), ())


def test_a_failed_move_is_left_to_the_user(
    conn: sqlite3.Connection, tmp_path: Path, folder: Path
) -> None:
    # [0012.29] [0012.31] the file at both paths after a crash: never undone
    crash(tmp_path / "journal.db", folder, planned(folder), {folder / B: "exit-before"})
    os.link(folder / MOVED[A], folder / A)
    recover(conn)
    assert plan_undo(conn, 1) == UndoPlan(1, folder, (), ())


def test_a_move_undone_is_not_taken_again(conn: sqlite3.Connection, folder: Path) -> None:
    # [0012.29]
    sorted_out(conn, folder)
    undo(conn, plan_undo(conn, 1))
    assert plan_undo(conn, 1) == UndoPlan(1, folder, (), ())


def test_a_move_whose_undo_was_rolled_back_is_taken_again(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.29] not undone yet: its undo did not happen
    sorted_out(conn, folder)
    stopped = undo(conn, plan_undo(conn, 1), rename=FlakyRename({folder / MOVED[B]: "before"}))
    assert stopped.state is BatchState.ROLLED_BACK
    assert names(plan_undo(conn, 1)) == [A, B, C]


def test_what_an_undo_left_undone_is_taken_by_the_next(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.29] the undo stopped and a, back, could not be sorted again: b and c are left
    sorted_out(conn, folder)
    rename = FlakyRename({folder / MOVED[B]: "before", folder / A: "before"})
    stopped = undo(conn, plan_undo(conn, 1), rename=rename)
    assert (stopped.state, stopped.left) == (BatchState.FAILED, (folder / A,))
    assert names(plan_undo(conn, 1)) == [B, C]


def test_an_undo_batch_cannot_be_undone(conn: sqlite3.Connection, folder: Path) -> None:
    # [0012.29] organize again instead
    sorted_out(conn, folder)
    undo(conn, plan_undo(conn, 1))
    with pytest.raises(UndoRefused) as refused:
        plan_undo(conn, 2)
    assert (refused.value.batch_id, refused.value.reason) == (2, UndoReason.UNDO_BATCH)


def test_a_batch_that_does_not_exist_cannot_be_undone(conn: sqlite3.Connection) -> None:
    # [0012.29]
    with pytest.raises(UndoRefused) as refused:
        plan_undo(conn, 7)
    assert (refused.value.batch_id, refused.value.reason) == (7, UndoReason.NOT_FOUND)


def test_a_pending_batch_is_recovered_before_it_is_undone(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.29] the command line recovers first; a pending batch says nothing true yet
    begin(conn, folder, [(folder / A, folder / MOVED[A], identity(folder / A))], lambda: 1)
    with pytest.raises(UndoRefused) as refused:
        plan_undo(conn, 1)
    assert refused.value.reason is UndoReason.PENDING


def test_the_undo_reasons_are_pinned() -> None:
    # [0012.29]
    assert [reason.value for reason in UndoReason] == ["not_found", "undo_batch", "pending"]


# --- what is at the destination (item 30) -------------------------------------------------------


def test_a_file_edited_after_sorting_still_goes_back(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.30] still the user's document; the undo plan takes it as it is now
    sorted_out(conn, folder)
    edited = write(folder / MOVED[B], b"edited after sorting")
    undo_plan = plan_undo(conn, 1)
    (move,) = [m for m in undo_plan.moves if m.destination.name == B]
    assert (move.size, move.mtime_ns) == (edited.lstat().st_size, edited.lstat().st_mtime_ns)
    assert undo(conn, undo_plan).state is BatchState.DONE
    assert files(folder)[B] == b"edited after sorting"


def test_a_missing_file_stays_missing(conn: sqlite3.Connection, zone: Path, folder: Path) -> None:
    # [0012.30]
    sorted_out(conn, folder)
    (folder / MOVED[A]).rename(zone / "kept.jpg")
    undo_plan = plan_undo(conn, 1)
    assert names(undo_plan) == [B, C]
    assert undo_plan.stays == (Stay(folder / MOVED[A], StayReason.MISSING),)


def test_a_file_that_cannot_be_looked_at_counts_as_missing(
    conn: sqlite3.Connection, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.30] as far as the undo can tell; the detail says why
    sorted_out(conn, folder)
    deny_stat(monkeypatch, folder / MOVED[A])
    undo_plan = plan_undo(conn, 1)
    assert names(undo_plan) == [B, C]
    assert undo_plan.stays == (Stay(folder / MOVED[A], StayReason.MISSING, "Permission denied"),)


def test_a_link_or_a_directory_at_the_destination_stays(
    conn: sqlite3.Connection, zone: Path, folder: Path
) -> None:
    # [0012.30] never followed, never entered
    sorted_out(conn, folder)
    (folder / MOVED[A]).rename(zone / "kept.jpg")
    (folder / MOVED[A]).symlink_to(zone / "kept.jpg")
    (folder / MOVED[B]).rename(zone / "kept.pdf")
    (folder / MOVED[B]).mkdir()
    undo_plan = plan_undo(conn, 1)
    assert names(undo_plan) == [C]
    assert undo_plan.stays == (
        Stay(folder / MOVED[A], StayReason.NOT_REGULAR),
        Stay(folder / MOVED[B], StayReason.NOT_REGULAR),
    )


def test_a_taken_source_is_never_overwritten(conn: sqlite3.Connection, folder: Path) -> None:
    # [0012.30] a newcomer at a's old name: a stays sorted
    sorted_out(conn, folder)
    write(folder / A, b"newcomer")
    undo_plan = plan_undo(conn, 1)
    assert names(undo_plan) == [B, C]
    assert undo_plan.stays == (Stay(folder / MOVED[A], StayReason.CONFLICT),)


def test_a_source_that_cannot_be_looked_at_counts_as_taken(
    conn: sqlite3.Connection, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.30]
    sorted_out(conn, folder)
    deny_stat(monkeypatch, folder / A)
    assert plan_undo(conn, 1).stays == (
        Stay(folder / MOVED[A], StayReason.CONFLICT, "Permission denied"),
    )


def test_preflight_checks_the_undo_plan(
    conn: sqlite3.Connection, folder: Path, scan: ScanContext
) -> None:
    # [0012.30] as item 19: changed since the undo plan, or held open
    sorted_out(conn, folder)
    undo_plan = plan_undo(conn, 1)
    write(folder / MOVED[B], b"changed since the undo plan")
    context = dataclasses.replace(scan, open_files=FakeOpenFiles([folder / MOVED[C]]))
    cleared, refused = check(undo_plan.moves, folder, context)
    assert [move.destination.name for move in cleared] == [A]
    assert [(r.path, r.reason.value) for r in refused] == [
        (folder / MOVED[B], "changed"),
        (folder / MOVED[C], "open_file"),
    ]


def test_an_undo_batch_crashed_is_recovered_like_any_batch(
    conn: sqlite3.Connection, tmp_path: Path, folder: Path
) -> None:
    # [0012.29] [0012.31] a move of either kind of batch, with its own source and destination
    sorted_out(conn, folder)
    undo_plan = plan_undo(conn, 1)
    moves = [(move.source, move.destination) for move in undo_plan.moves]
    undoes = [move.undoes for move in undo_plan.moves]
    crash(tmp_path / "journal.db", folder, moves, {folder / MOVED[B]: "exit-after"}, undoes)
    report = recover(conn)
    assert report.batches == (
        RecoveredBatch(
            2, BatchState.FAILED, (folder / A, folder / B), kind=BatchKind.UNDO, undoing=1
        ),
    )
    assert files(folder) == content({A: A, B: B, C: MOVED[C]})
    assert names(plan_undo(conn, 1)) == [C]  # a and b are back: c only is left to undo
