"""On Windows a directory with a reparse point is a link (decision 0017, item 11).

A junction or a mount point is a directory that leads elsewhere, and Windows's ``lstat`` says
it is a directory, with ``FILE_ATTRIBUTE_REPARSE_POINT`` among its file attributes. Where a
category directory would be, it is not one: its category stays in place at plan time, its
files are refused at move time, and a batch that meets it stops, as with a link or a file
there (0012 items 18, 19 and 26). This system has no junction: ``reparse_point`` makes
``lstat`` say what Windows's says of one.
"""

import dataclasses
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from fakes import reparse_point
from kresorter.core.preflight import RefusalReason
from kresorter.core.scanner import ScanContext
from kresorter.environment import detect_platform
from kresorter.organize.mover import BatchState, carry_out, check
from kresorter.organize.planner import StayReason, plan
from kresorter.storage.db import connect
from support.moves import (
    MOVED,
    SOURCES,
    B,
    FlakyRename,
    content,
    files,
    planned,
    three_files,
    where,
)


@pytest.fixture
def windows(scan: ScanContext) -> ScanContext:
    return dataclasses.replace(scan, platform="windows")


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    yield connection
    connection.close()


def test_a_junction_where_a_category_directory_would_be_keeps_its_category(
    zone: Path, windows: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0017.11] category_blocked, as a link there (0012.18); the others move
    folder = three_files(zone)
    (folder / "Documents").mkdir()
    reparse_point(monkeypatch, folder / "Documents")
    found = plan(folder, windows)
    assert [(s.path.name, s.reason, s.detail) for s in found.stays] == [
        ("Documents", StayReason.NOT_REGULAR, ""),
        (B, StayReason.CATEGORY_BLOCKED, ""),
    ]
    assert [m.source.name for m in found.moves] == ["a.jpg", "c.mp3"]


def test_a_junction_made_after_the_plan_refuses_its_files(
    zone: Path, windows: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0017.11] at move time, as a category path that is not a directory (0012.19)
    folder = three_files(zone)
    moves = plan(folder, windows).moves
    (folder / "Documents").mkdir()
    reparse_point(monkeypatch, folder / "Documents")
    cleared, refused = check(moves, folder, windows)
    assert [m.source.name for m in cleared] == ["a.jpg", "c.mp3"]
    assert [(r.path.name, r.reason, r.detail) for r in refused] == [
        (B, RefusalReason.CONFLICT, f"{folder / 'Documents'}: not a directory")
    ]


def test_a_junction_made_after_the_check_stops_the_batch(
    conn: sqlite3.Connection, zone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0017.11] nothing goes where it leads; the others go back (0012.26, 0012.27)
    folder = three_files(zone)
    (folder / "Documents").mkdir()
    reparse_point(monkeypatch, folder / "Documents")
    rename = FlakyRename()
    result = carry_out(conn, folder, planned(folder), rename=rename)
    assert result.state is BatchState.ROLLED_BACK
    assert (folder / B, folder / MOVED[B]) not in rename.calls
    assert list((folder / "Documents").iterdir()) == []
    assert where(conn, folder) == SOURCES
    assert files(folder) == content(SOURCES)


def test_elsewhere_a_directory_is_what_lstat_says(tmp_path: Path) -> None:
    # [0017.11] Linux's and macOS's lstat says no file attributes: a reparse point is Windows's
    if detect_platform() == "windows":
        pytest.skip("not on Windows")
    assert not hasattr(os.lstat(tmp_path), "st_file_attributes")
