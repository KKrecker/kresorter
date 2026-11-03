"""The mover (decision 0012, items 19 and 25-28): every planned file checked again right before
the batch, then journal before move, rename only, all or nothing as far as the disk allows.

Three files, one per category, each holding its own name (``support.moves``). After every
batch ``where`` (the journal) and ``files`` (the disk) must agree exactly: each file where the
journal says, every foreign file as it was, nothing overwritten, nothing deleted.
"""

import dataclasses
import ntpath
import os
import sqlite3
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, deny_stat, make_policy, other_device
from kresorter.core.open_files import ShareModeChecker
from kresorter.core.preflight import RefusalReason
from kresorter.core.scanner import ScanContext
from kresorter.organize.journal import identity, journaled
from kresorter.organize.mover import BatchState, carry_out, check
from kresorter.organize.planner import Move, plan
from kresorter.storage.db import connect
from support.files import write
from support.host import as_kept
from support.kernel import HoldingKernel
from support.moves import (
    MOVED,
    SOURCES,
    A,
    B,
    C,
    FlakyRename,
    Interrupt,
    batches,
    content,
    crash,
    files,
    planned,
    three_files,
    where,
)

GENERIC_READ = 0x80000000


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    yield connection
    connection.close()


@pytest.fixture
def folder(zone: Path) -> Path:
    return three_files(zone)


def test_a_batch_moves_every_file(conn: sqlite3.Connection, folder: Path) -> None:
    # [0012.25] [0012.27]
    result = carry_out(conn, folder, planned(folder))
    assert (result.state, result.left) == (BatchState.DONE, ())
    assert where(conn, folder) == MOVED
    assert files(folder) == content(MOVED)


# --- checked again right before the batch (item 19) ---------------------------------------------


def refused(folder: Path, context: ScanContext, moves: tuple[Move, ...]) -> list[tuple[str, str]]:
    """What ``check`` refuses of ``moves``, by name and reason; it keeps the others in order."""
    return [(name, reason) for name, reason, _ in explained(folder, context, moves)]


def explained(
    folder: Path, context: ScanContext, moves: tuple[Move, ...]
) -> list[tuple[str, str, str]]:
    """``refused``, each refusal with its detail."""
    cleared, refusals = check(moves, folder, context)
    names = {r.path.name for r in refusals}
    assert [m.source.name for m in cleared] == [
        m.source.name for m in moves if m.source.name not in names
    ]
    return [(r.path.name, r.reason.value, r.detail) for r in refusals]


def test_a_file_unchanged_since_the_plan_is_cleared(folder: Path, scan: ScanContext) -> None:
    # [0012.19] the open-file check is asked of every file
    moves = plan(folder, scan).moves
    assert refused(folder, scan, moves) == []
    assert isinstance(scan.open_files, FakeOpenFiles)
    assert sorted(p.name for p in scan.open_files.calls) == [A, B, C]


def test_a_file_a_program_holds_open_is_refused(folder: Path, scan: ScanContext) -> None:
    # [0012.19]
    moves = plan(folder, scan).moves
    context = dataclasses.replace(scan, open_files=FakeOpenFiles([folder / B]))
    assert refused(folder, context, moves) == [(B, "open_file")]


def test_on_windows_the_share_mode_check_runs_right_before_the_batch(
    folder: Path, scan: ScanContext
) -> None:
    # [0017.5] another process holds b, sharing deletion or not: b stays; the check asks to read
    # only and shares nothing, so it disturbs no holder (0016 item 3), and closes what it opened
    moves = plan(folder, scan).moves
    kernel = HoldingKernel(B)
    windows = dataclasses.replace(scan, open_files=ShareModeChecker(kernel), platform="windows")
    assert refused(folder, windows, moves) == [(B, "open_file")]
    opened = [call for call in kernel.calls if call[0] == "CreateFileW"]
    assert sorted(ntpath.basename(str(call[1])) for call in opened) == sorted([A, B, C])
    assert {call[2:4] for call in opened} == {(GENERIC_READ, 0)}
    assert [call[0] for call in kernel.calls].count("CloseHandle") == 2


def test_a_file_the_policy_blocks_now_is_refused(
    tmp_path: Path, folder: Path, data_dir: Path, scan: ScanContext
) -> None:
    # [0012.19]
    moves = plan(folder, scan).moves
    policy = make_policy(tmp_path, folder / B, app_data_dir=data_dir)
    assert refused(folder, dataclasses.replace(scan, policy=policy), moves) == [(B, "blocked")]


def test_a_file_changed_since_the_plan_is_refused(folder: Path, scan: ScanContext) -> None:
    # [0012.19] the size and mtime_ns of the plan
    moves = plan(folder, scan).moves
    write(folder / B, b"a longer document")
    assert refused(folder, scan, moves) == [(B, "changed")]


def test_a_file_gone_since_the_plan_is_refused(zone: Path, folder: Path, scan: ScanContext) -> None:
    # [0012.19]
    moves = plan(folder, scan).moves
    (folder / B).rename(zone / B)
    assert refused(folder, scan, moves) == [(B, "not_found")]


def test_a_folder_swapped_for_a_link_refuses_every_file(
    zone: Path, folder: Path, scan: ScanContext
) -> None:
    # [0012.19] a parent not swapped for a link
    moves = plan(folder, scan).moves
    folder.rename(zone / "elsewhere")
    folder.symlink_to(zone / "elsewhere")
    assert refused(folder, scan, moves) == [(name, "parent_swapped") for name in (A, C, B)]


def test_a_file_on_another_device_is_refused(
    folder: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.19] on the folder's device; no detail
    moves = plan(folder, scan).moves
    other_device(monkeypatch, folder / B)
    assert explained(folder, scan, moves) == [(B, "cross_device", "")]


def test_a_category_directory_on_another_device_is_refused(
    folder: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.19] [0012.26] never copied into
    (folder / "Documents").mkdir()
    moves = plan(folder, scan).moves
    other_device(monkeypatch, folder / "Documents")
    assert explained(folder, scan, moves) == [(B, "cross_device", str(folder / "Documents"))]


def test_a_destination_taken_since_the_plan_is_refused(folder: Path, scan: ScanContext) -> None:
    # [0012.19] its destination still free; the detail names it
    moves = plan(folder, scan).moves
    write(folder / MOVED[B], b"theirs")
    assert explained(folder, scan, moves) == [(B, "conflict", str(folder / MOVED[B]))]


def test_a_destination_that_cannot_be_looked_at_is_refused(
    folder: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.19] free means not found, nothing else
    (folder / "Documents").mkdir()
    moves = plan(folder, scan).moves
    deny_stat(monkeypatch, folder / MOVED[B])
    assert explained(folder, scan, moves) == [(B, "conflict", "Permission denied")]


def test_a_category_path_no_longer_a_directory_is_refused(
    zone: Path, folder: Path, scan: ScanContext
) -> None:
    # [0012.19] a link to a directory is not one
    moves = plan(folder, scan).moves
    (zone / "elsewhere").mkdir()
    (folder / "Documents").symlink_to(zone / "elsewhere")
    not_one = f"{folder / 'Documents'}: not a directory"
    assert explained(folder, scan, moves) == [(B, "conflict", not_one)]


def test_a_category_path_that_cannot_be_looked_at_is_refused(
    folder: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.19]
    moves = plan(folder, scan).moves
    deny_stat(monkeypatch, folder / "Documents")
    denied = f"{folder / 'Documents'}: Permission denied"
    assert explained(folder, scan, moves) == [(B, "unreadable", denied)]


def test_the_refusals_keep_the_reasons_of_the_quarantine() -> None:
    # [0012.19] one reason of its own: a taken destination
    assert RefusalReason.CONFLICT.value == "conflict"


# --- a rename that fails, forward ---------------------------------------------------------------


def test_a_rename_that_fails_before_moving_stops_and_rolls_back(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.27] b is refused: c is never tried, a goes back
    rename = FlakyRename({folder / B: "before"})
    result = carry_out(conn, folder, planned(folder), rename=rename)
    assert (result.state, result.left) == (BatchState.ROLLED_BACK, ())
    assert rename.calls == [
        (folder / A, folder / MOVED[A]),
        (folder / B, folder / MOVED[B]),
        (folder / MOVED[A], folder / A),
    ]
    assert where(conn, folder) == SOURCES
    assert files(folder) == content(SOURCES)


def test_a_rename_that_fails_after_moving_is_settled_by_the_disk(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.27] b moved before the error: the disk says so, and b goes back too, newest first
    rename = FlakyRename({folder / B: "after"})
    result = carry_out(conn, folder, planned(folder), rename=rename)
    assert result.state is BatchState.ROLLED_BACK
    assert rename.calls[2:] == [(folder / MOVED[B], folder / B), (folder / MOVED[A], folder / A)]
    assert where(conn, folder) == SOURCES
    assert files(folder) == content(SOURCES)


# --- a rename that fails, back: a partial rollback ----------------------------------------------


def test_a_move_back_that_fails_before_moving_leaves_its_file_done(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.27] b cannot go back; a, older, is still tried and goes back
    rename = FlakyRename({folder / C: "before", folder / MOVED[B]: "before"})
    result = carry_out(conn, folder, planned(folder), rename=rename)
    assert (result.state, result.left) == (BatchState.FAILED, (folder / MOVED[B],))
    expected = {A: A, B: MOVED[B], C: C}
    assert where(conn, folder) == expected
    assert files(folder) == content(expected)
    assert batches(conn) == ["failed"]


def test_a_move_back_that_fails_after_moving_is_settled_by_the_disk(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.27] b went back before the error: it is rolled_back, not left done
    rename = FlakyRename({folder / C: "before", folder / MOVED[B]: "after"})
    result = carry_out(conn, folder, planned(folder), rename=rename)
    assert (result.state, result.left) == (BatchState.ROLLED_BACK, ())
    assert where(conn, folder) == SOURCES
    assert files(folder) == content(SOURCES)


def test_a_newcomer_at_a_source_is_never_overwritten(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.27] while c is being moved a new a.jpg appears where a was: a stays sorted
    def newcomer() -> None:
        write(folder / A, b"newcomer")

    rename = FlakyRename({folder / C: "before"}, meanwhile={folder / C: newcomer})
    result = carry_out(conn, folder, planned(folder), rename=rename)
    assert (result.state, result.left) == (BatchState.FAILED, (folder / MOVED[A],))
    expected = {A: MOVED[A], B: B, C: C}
    assert where(conn, folder) == expected
    assert files(folder) == {**content(expected), A: b"newcomer"}


def test_a_destination_taken_since_the_check_stops_the_batch(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.26] [0012.27] theirs is never overwritten: b is not even renamed
    write(folder / MOVED[B], b"theirs")
    rename = FlakyRename()
    result = carry_out(conn, folder, planned(folder), rename=rename)
    assert result.state is BatchState.ROLLED_BACK
    assert (folder / B, folder / MOVED[B]) not in rename.calls
    assert where(conn, folder) == SOURCES
    assert files(folder) == {**content(SOURCES), MOVED[B]: b"theirs"}


def test_the_journal_keeps_each_file_as_it_was(conn: sqlite3.Connection, folder: Path) -> None:
    # [0012.24] [0012.25] device, inode, size and mtime_ns before the move; a rename keeps them
    before = {name: identity(folder / name) for name in (A, B, C)}
    result = carry_out(conn, folder, planned(folder))
    assert {m.source.name: m.file for m in journaled(conn, result.batch_id)} == before
    assert {name: identity(folder / MOVED[name]) for name in (A, B, C)} == before


def test_a_batch_needs_a_move(conn: sqlite3.Connection, folder: Path) -> None:
    with pytest.raises(ValueError, match="at least one move"):
        carry_out(conn, folder, [])
    assert batches(conn) == []


# --- journal before move, category directories after it (items 25, 26 and 28) -----------------


def test_nothing_moves_before_the_whole_batch_is_journaled(
    conn: sqlite3.Connection, tmp_path: Path, folder: Path
) -> None:
    # [0012.25] [0012.28] a crash right before the first rename: its directory only is made
    crash(tmp_path / "journal.db", folder, planned(folder), {folder / A: "exit-before"})
    assert batches(conn) == ["pending"]
    assert where(conn, folder) == {A: "pending", B: "pending", C: "pending"}
    assert files(folder) == content(SOURCES)
    assert sorted(p.name for p in folder.iterdir() if p.is_dir()) == ["Images"]


def test_category_directories_are_made_after_the_journal_with_the_default_mode(
    conn: sqlite3.Connection, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.28]
    made: list[tuple[str, list[str], dict[str, str]]] = []
    real = os.mkdir

    def mkdir(path: Path, mode: int = 0o777) -> None:
        made.append((Path(path).name, batches(conn), where(conn, folder)))
        real(path, mode)

    monkeypatch.setattr(os, "mkdir", mkdir)
    carry_out(conn, folder, planned(folder))
    assert made == [
        ("Images", ["pending"], {A: "pending", B: "pending", C: "pending"}),
        ("Documents", ["pending"], {A: MOVED[A], B: "pending", C: "pending"}),
        ("Audio", ["pending"], {A: MOVED[A], B: MOVED[B], C: "pending"}),
    ]
    umask = os.umask(0o022)
    os.umask(umask)
    modes = {
        stat.S_IMODE((folder / name).lstat().st_mode) for name in ("Images", "Documents", "Audio")
    }
    assert modes == {as_kept(0o777 & ~umask, directory=True)}


def test_an_existing_category_directory_is_used_as_it_is(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.28]
    write(folder / "Images" / "older.jpg", b"older")
    (folder / "Images").chmod(0o700)
    result = carry_out(conn, folder, planned(folder))
    assert result.state is BatchState.DONE
    assert stat.S_IMODE((folder / "Images").lstat().st_mode) == as_kept(0o700, directory=True)
    assert files(folder) == {**content(MOVED), "Images/older.jpg": b"older"}


def test_a_category_directory_that_cannot_be_made_stops_the_batch(
    conn: sqlite3.Connection, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.27] [0012.28] Images, already made, stays: organize deletes nothing (item 4)
    real = os.mkdir

    def mkdir(path: Path, mode: int = 0o777) -> None:
        if Path(path).name == "Documents":
            raise PermissionError(13, "Permission denied", str(path))
        real(path, mode)

    monkeypatch.setattr(os, "mkdir", mkdir)
    rename = FlakyRename()
    result = carry_out(conn, folder, planned(folder), rename=rename)
    assert result.state is BatchState.ROLLED_BACK
    assert "Permission denied" in (result.error or "")
    assert rename.calls == [(folder / A, folder / MOVED[A]), (folder / MOVED[A], folder / A)]
    assert where(conn, folder) == SOURCES
    assert files(folder) == content(SOURCES)
    assert (folder / "Images").is_dir()


def test_a_category_path_that_became_a_link_stops_the_batch(
    conn: sqlite3.Connection, zone: Path, folder: Path
) -> None:
    # [0012.26] [0012.27] never followed: nothing goes where the link leads
    (zone / "elsewhere").mkdir()
    (folder / "Documents").symlink_to(zone / "elsewhere")
    rename = FlakyRename()
    result = carry_out(conn, folder, planned(folder), rename=rename)
    assert result.state is BatchState.ROLLED_BACK
    assert (folder / B, folder / MOVED[B]) not in rename.calls
    assert list((zone / "elsewhere").iterdir()) == []
    assert where(conn, folder) == SOURCES


def test_a_category_directory_on_another_device_stops_the_batch(
    conn: sqlite3.Connection, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.26] [0012.27] refused, never copied into
    (folder / "Documents").mkdir()
    other_device(monkeypatch, folder / "Documents")
    rename = FlakyRename()
    result = carry_out(conn, folder, planned(folder), rename=rename)
    assert result.state is BatchState.ROLLED_BACK
    assert (folder / B, folder / MOVED[B]) not in rename.calls
    assert files(folder) == content(SOURCES)


def test_an_interrupt_during_the_rollback_stops_everything(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.27] the batch stays pending, and what the journal says is true: b and a never went back
    rename = FlakyRename({folder / C: "before", folder / MOVED[B]: "interrupt"})
    with pytest.raises(Interrupt):
        carry_out(conn, folder, planned(folder), rename=rename)
    expected = {A: MOVED[A], B: MOVED[B], C: C}
    assert batches(conn) == ["pending"]
    assert where(conn, folder) == expected
    assert files(folder) == content(expected)


# --- interrupts and crashes ---------------------------------------------------------------------


def test_an_interrupt_rolls_back_then_is_raised_again(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # [0012.27] KeyboardInterrupt and the like: the rollback runs first
    with pytest.raises(Interrupt):
        carry_out(conn, folder, planned(folder), rename=FlakyRename({folder / B: "interrupt"}))
    assert batches(conn) == ["rolled_back"]
    assert where(conn, folder) == SOURCES
    assert files(folder) == content(SOURCES)


def test_after_a_crash_the_journal_says_nothing_untrue(
    conn: sqlite3.Connection, tmp_path: Path, folder: Path
) -> None:
    # [0012.25] [0012.27] the crash comes right after b moved, before its done was written
    crash(tmp_path / "journal.db", folder, planned(folder), {folder / B: "exit-after"})
    assert batches(conn) == ["pending"]
    assert where(conn, folder) == {A: MOVED[A], B: "pending", C: "pending"}
    assert files(folder) == content({A: MOVED[A], B: MOVED[B], C: C})
