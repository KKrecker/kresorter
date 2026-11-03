"""Live on Windows (decision 0017, item 13; skipped elsewhere): organize with the running
system's context, in a temporary profile (``support.profile``).

What this machine checks with a Windows context and fakes is shown here on Windows itself: the
share-mode check before the batch, renames tried again while a handle refuses them, the path
limit, a junction where a category directory would be, a folder under the ``OneDrive``
variable. A file "this process holds" is opened with ``open``, which shares reading and writing
but not deletion, so a rename of it fails as Windows fails it for another program.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from kresorter.core.open_files import ShareModeChecker
from kresorter.core.scanner import ScanContext
from kresorter.organize.mover import BatchState, carry_out
from kresorter.organize.platforms import DELAYS, renamer
from kresorter.organize.synced import WindowsSyncedFolders
from kresorter.storage.db import connect
from support.cli import run
from support.files import write
from support.holder import held_by_a_child
from support.moves import MOVED, SOURCES, A, B, C, content, files, planned, three_files
from support.profile import windows_context

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="live Windows organize")

MTIME_NS = 1_600_000_000_123_456_700  # NTFS keeps 100 ns
CATEGORIES = ("Audio", "Documents", "Images")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path.resolve() / "Alice"


@pytest.fixture
def context(home: Path) -> ScanContext:
    return windows_context(home)


def move(folder: Path, context: ScanContext) -> tuple[int, list[str], str]:
    code, out, err = run(["organize", "move", str(folder), "--yes"], context)
    return code, out.splitlines(), err


def test_live_the_context_is_the_running_systems(context: ScanContext) -> None:
    # [0017.13] the share-mode check and the synced folders Windows names
    assert isinstance(context.open_files, ShareModeChecker)
    assert isinstance(context.synced, WindowsSyncedFolders)


def test_live_move_then_undo_puts_every_file_back(context: ScanContext, home: Path) -> None:
    # [0017.13] each with its mtime_ns
    folder = three_files(home)
    for name in (A, B, C):
        os.utime(folder / name, ns=(MTIME_NS, MTIME_NS))

    code, lines, err = move(folder, context)

    assert (code, err) == (0, ""), lines
    assert files(folder) == content(MOVED)

    code, out, err = run(["organize", "undo", "1", "--yes"], context)

    assert (code, err) == (0, ""), out
    assert files(folder) == content(SOURCES)
    assert [(folder / name).stat().st_mtime_ns for name in (A, B, C)] == [MTIME_NS] * 3
    assert sorted(p.name for p in folder.iterdir() if p.is_dir()) == list(CATEGORIES)


def test_live_a_file_a_child_process_holds_stays(context: ScanContext, home: Path) -> None:
    # [0017.13] refused open_file by the check before the batch; the others move
    folder = three_files(home)

    with held_by_a_child(folder / B):
        code, lines, _ = move(folder, context)

    assert code == 1
    assert f"  open_file: {folder / B}" in lines
    assert files(folder) == content({A: MOVED[A], B: B, C: MOVED[C]})


def test_live_a_rename_held_open_moves_once_the_file_is_closed(tmp_path: Path, home: Path) -> None:
    # [0017.13] the holder closes it during the second wait: the third try moves it
    folder = three_files(home)
    waits: list[float] = []

    with (folder / B).open("rb") as held:

        def sleep(seconds: float) -> None:
            waits.append(seconds)
            if len(waits) == 2:
                held.close()

        with closing(connect(tmp_path / "journal.db")) as conn:
            result = carry_out(
                conn, folder, planned(folder), rename=renamer("windows", sleep=sleep)
            )

    assert (result.state, waits) == (BatchState.DONE, [0.1, 0.2])
    assert files(folder) == content(MOVED)


def test_live_a_rename_held_through_every_try_stops_and_rolls_back(
    tmp_path: Path, home: Path
) -> None:
    # [0017.13] six tries, then the batch stops and the moved photo goes back
    folder = three_files(home)
    waits: list[float] = []

    with (folder / B).open("rb"), closing(connect(tmp_path / "journal.db")) as conn:
        result = carry_out(
            conn, folder, planned(folder), rename=renamer("windows", sleep=waits.append)
        )

    assert result.state is BatchState.ROLLED_BACK
    assert (result.error or "").startswith("[WinError 32]")
    assert waits == list(DELAYS)
    assert files(folder) == content(SOURCES)


def test_live_a_file_whose_destination_would_pass_259_stays(
    context: ScanContext, home: Path
) -> None:
    # [0017.13] a folder of 200 characters: Documents has 210, the report 256 and would have 266
    pad = 200 - len(str(home / "Downloads")) - 1
    if pad < 1:
        pytest.skip("the temporary folder is too deep for a folder of 200 characters")
    folder = home / ("p" * pad) / "Downloads"
    report = write(folder / ("n" * 51 + ".pdf"), b"report")
    write(folder / A, A.encode())
    assert (len(str(folder)), len(str(report))) == (200, 256)

    code, lines, err = move(folder, context)

    assert (code, err) == (0, ""), lines
    assert f"  path_too_long: {report.name} (266 > 259)" in lines
    assert report.read_bytes() == b"report"
    assert (folder / "Images" / A).read_bytes() == A.encode()


def test_live_a_junction_where_a_category_directory_would_be_keeps_its_category(
    context: ScanContext, home: Path, tmp_path: Path
) -> None:
    # [0017.11] [0017.13] lstat says what the fake of the tests elsewhere says; nothing goes
    # where the junction leads
    folder = three_files(home)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    junction = folder / "Documents"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(elsewhere)],
        check=True,
        capture_output=True,
    )
    info = os.lstat(junction)
    assert stat.S_ISDIR(info.st_mode)
    assert getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT

    code, lines, err = move(folder, context)

    assert (code, err) == (0, ""), lines
    assert f"  category_blocked: {B}" in lines
    assert (folder / B).read_bytes() == B.encode()
    assert list(elsewhere.iterdir()) == []


def test_live_a_folder_under_the_onedrive_variable_is_refused(home: Path) -> None:
    # [0017.13] as a whole, whatever the registry names
    onedrive = home / "OneDrive"
    folder = three_files(onedrive)
    context = windows_context(home, OneDrive=str(onedrive))

    assert run(["organize", "move", str(folder), "--yes"], context) == (
        1,
        f"Refused: {folder}: cloud_sync ({onedrive})\n",
        "",
    )
    assert files(folder) == content(SOURCES)


def test_live_a_folder_given_in_another_case_is_sorted_as_windows_spells_it(
    context: ScanContext, home: Path
) -> None:
    # [0017.12] [0017.13]
    folder = three_files(home)
    given = home / "downloads"

    code, lines, err = move(given, context)

    assert (code, err) == (0, ""), lines
    assert lines[0] == f"Moved 3 files, 15 B, in {folder} (batch 1):"
    assert files(folder) == content(MOVED)
