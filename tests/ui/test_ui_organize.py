"""The Organize page: where organize does not move files, why, and nothing else; elsewhere a
folder's plan, the batch carried out after confirmation and named, the batches and their undo
(decision 0014, items 14 and 23). The plan is made again inside the session: only the confirmed
moves it still holds unchanged are carried out, and what no longer holds is reported."""

import functools
import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QGridLayout, QTreeWidget, QTreeWidgetItem, QWidget
from pytestqt.qtbot import QtBot

from fakes import FakeOpenFiles, UnreliableOpenFiles
from kresorter.core.heuristics import Platform
from kresorter.core.open_files import OpenFileChecker
from kresorter.organize.mover import Rename
from kresorter.organize.planner import StayReason
from kresorter.ui import sessions
from kresorter.ui.dialogs import Confirmation
from kresorter.ui.organize import BATCHES_WIDTH, CATEGORY_ICONS, OrganizePage
from kresorter.ui.parts import QUIET, SECONDARY, Field
from kresorter.ui.shown import moment
from kresorter.ui.theme import LIGHT
from kresorter.ui.window import Window
from support.cli import run, scan_context
from support.files import write
from support.journal import pending_quarantine, query
from support.moves import A, B, C, FlakyRename, files, renaming, three_files
from support.window import FakeDialogs, children, environment, make_window, wait_idle

UNSORTED = {A: b"a.jpg", B: b"b.pdf", C: b"c.mp3"}
SORTED = {f"Images/{A}": b"a.jpg", f"Documents/{B}": b"b.pdf", f"Audio/{C}": b"c.mp3"}
STAYING = {"old/inside.jpg": b"inside", ".hidden": b"hidden", "old.tmp": b"old"}
STAYS = [
    ("old", "Not a regular file"),
    (".hidden", "The folder's own file"),
    ("old.tmp", "Junk: for the cleanup: temp-files"),
]
CARDS = [
    ("Images", "1 file · 5 B", "Images", "a.jpg"),
    ("Audio", "1 file · 5 B", "Audio", "c.mp3"),
    ("Documents", "1 file · 5 B", "Documents", "b.pdf"),
]
PLAN = (CARDS, STAYS)
NO_PLAN: tuple[list[tuple[str, str, str, str]], list[tuple[str, str]]] = ([], [])


@pytest.fixture
def folder(zone: Path) -> Path:
    """``three_files``, with a subdirectory, the folder's metadata and junk beside them."""
    folder = three_files(zone)
    write(folder / "old" / "inside.jpg", b"inside")
    write(folder / ".hidden", b"hidden")
    write(folder / "old.tmp", b"old")
    return folder


@pytest.fixture
def dialogs(folder: Path) -> FakeDialogs:
    return FakeDialogs(folders=[folder])


def _window(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    *,
    open_files: OpenFileChecker | None = None,
) -> Window:
    made = environment(tmp_path, zone, data_dir, open_files=open_files)
    window = make_window(qtbot, made, dialogs=dialogs)
    _opened(qtbot, window)
    return window


@pytest.fixture
def window(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> Window:
    return _window(qtbot, tmp_path, zone, data_dir, dialogs)


def _opened(qtbot: QtBot, window: Window) -> None:
    window.show_page("organize")
    wait_idle(qtbot, window)


def _planned(qtbot: QtBot, window: Window) -> None:
    """Choose the folder the dialog gives and wait for its plan."""
    window.organize.choose_button.click()
    wait_idle(qtbot, window)


def _sorted(qtbot: QtBot, window: Window, dialogs: FakeDialogs) -> None:
    """Plan the folder and move its files: batch 1; the questions asked are forgotten."""
    _planned(qtbot, window)
    window.organize.move_button.click()
    wait_idle(qtbot, window)
    dialogs.asked.clear()


def _undo(qtbot: QtBot, window: Window, batch_id: int) -> None:
    page = window.organize
    page.batches.setCurrentItem(page.batch_row(batch_id))
    page.undo_button.click()
    wait_idle(qtbot, window)


def _rows(tree: QTreeWidget) -> list[QTreeWidgetItem]:
    root = tree.invisibleRootItem()
    return children(root)


def _at(grid: QGridLayout, row: int, column: int) -> QWidget | None:
    item = grid.itemAtPosition(row, column)
    return None if item is None else item.widget()


def _cards(window: Window) -> list[tuple[str, str, str, str]]:
    """Each category's card: its category, its files and size, its name, its first names."""
    return [
        (card.category, card.amount.text(), card.name.text(), card.names.text())
        for card in window.organize.cards
    ]


def _stays(window: Window) -> list[tuple[str, str]]:
    """Each file that stays: its name, its reason."""
    return [(row.text(0), row.text(1)) for row in _rows(window.organize.stays)]


def _plan(window: Window) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, str]]]:
    return _cards(window), _stays(window)


def _batches(window: Window) -> list[tuple[str, str]]:
    """Each batch: its id and time, then its files moved, kind and state."""
    return [(row.text(0), row.data(0, SECONDARY)) for row in _rows(window.organize.batches)]


def _batch(data_dir: Path, batch_id: int, note: str) -> tuple[str, str]:
    return (f"Batch {batch_id} · {_when(data_dir, batch_id)}", note)


def _when(data_dir: Path, batch_id: int) -> str:
    [(created,)] = query(data_dir, "SELECT created_at_ns FROM move_batches WHERE id = ?", batch_id)
    assert isinstance(created, int)
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(created / 1e9))


def _no_batch(data_dir: Path) -> bool:
    return query(data_dir, "SELECT COUNT(*) FROM move_batches") == [(0,)]


def _lines(window: Window) -> list[str]:
    return window.organize.result.text().splitlines()


# --- where organize does not move files [0014.23] ------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "open_files", "why"),
    [
        (
            "windows",
            FakeOpenFiles(),
            [
                "Windows can refuse to move files in use",
                "Windows limits path length",
                "Folders synced to the cloud",
            ],
        ),
        ("linux", UnreliableOpenFiles(), ["Files in use cannot be recognized here"]),
    ],
    ids=["windows", "no-open-file-check"],
)
def test_where_organize_does_not_move_files_the_page_says_why_and_nothing_else(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    platform: Platform,
    open_files: OpenFileChecker,
    why: list[str],
) -> None:
    # [0014.23] 0012 item 37; not even the batches are read.
    blocked = environment(tmp_path, zone, data_dir, platform=platform, open_files=open_files)
    window = make_window(qtbot, blocked)
    _opened(qtbot, window)
    page = window.organize
    assert page.blocked.text().splitlines() == [
        "Organize does not move files on this system:",
        *why,
    ]
    assert page.blocked.isVisible()
    assert not page.controls.isVisible()
    assert not data_dir.exists()


# --- the plan [0014.23] --------------------------------------------------------------------------


def test_a_folder_s_plan_shows_the_moves_by_category_and_what_stays(
    qtbot: QtBot, window: Window, folder: Path, data_dir: Path
) -> None:
    # [0014.23] [0014.52]
    page = window.organize
    assert not page.blocked.isVisible()
    assert page.controls.isVisible()
    assert page.choose_button.text() == "Choose folder…"
    assert not page.move_button.isEnabled()
    _planned(qtbot, window)
    assert page.summary.text() == ""
    assert _plan(window) == PLAN
    assert page.will.text() == "3 files will move into 3 folders."
    assert page.move_button.text() == "Sort…"
    assert page.move_button.isEnabled()
    assert files(folder) == {**UNSORTED, **STAYING}
    assert _no_batch(data_dir)


def test_a_folder_where_every_file_moves_has_nothing_that_stays(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, zone: Path
) -> None:
    # [0014.23] [0014.52]
    plain = three_files(zone / "Plain")
    dialogs.folders = [plain]
    _planned(qtbot, window)
    assert _plan(window) == (CARDS, [])
    assert not window.organize.staying.isVisible()
    assert window.organize.bar.isVisible()


def test_a_folder_with_nothing_to_move_says_so(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, zone: Path
) -> None:
    # [0014.23] [0014.52]
    quiet = zone / "Quiet"
    write(quiet / ".hidden", b"hidden")
    dialogs.folders = [quiet]
    _planned(qtbot, window)
    page = window.organize
    assert page.summary.text() == f"Nothing to move in {quiet}."
    assert _plan(window) == ([], [(".hidden", "The folder's own file")])
    assert (page.state.text(), page.bar.isVisible()) == ("", False)
    assert not page.move_button.isEnabled()


def test_a_refused_folder_is_planned_nothing(qtbot: QtBot, window: Window, folder: Path) -> None:
    # [0014.23] A folder organize does not sort (0012 item 8).
    write(folder / "Makefile", b"all:")
    _planned(qtbot, window)
    page = window.organize
    assert page.summary.text() == f"Refused: {folder}: A project: Makefile"
    assert _plan(window) == NO_PLAN
    assert not page.move_button.isEnabled()


def test_a_folder_dialog_closed_plans_nothing(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs
) -> None:
    # [0014.23] [0014.52]
    dialogs.folders = [None]
    _planned(qtbot, window)
    page = window.organize
    assert page.summary.text() == ""
    assert _plan(window) == NO_PLAN
    assert (page.folder.text(), page.choose_button.text()) == ("", "Choose folder…")


def test_a_plan_made_again_replaces_the_one_shown(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path, zone: Path
) -> None:
    # [0014.23] [0014.52]
    quiet = zone / "Quiet"
    write(quiet / ".hidden", b"hidden")
    dialogs.folders = [folder, quiet]
    _planned(qtbot, window)
    _planned(qtbot, window)
    page = window.organize
    assert _plan(window) == ([], [(".hidden", "The folder's own file")])
    assert page.categories.count() == 0
    assert not page.move_button.isEnabled()


# --- the batch [0014.14] [0014.23] ---------------------------------------------------------------


def test_moving_asks_first_and_a_cancel_moves_nothing(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path, data_dir: Path
) -> None:
    # [0014.3] [0014.23]
    _planned(qtbot, window)
    dialogs.answer = False
    window.organize.move_button.click()
    wait_idle(qtbot, window)
    assert dialogs.asked == [
        Confirmation(
            title="Sort files",
            text=f"Move 3 files (15 B) into category folders in {folder}? Undo moves them back.",
            details=("a.jpg → Images/", "c.mp3 → Audio/", "b.pdf → Documents/"),
            action="Sort files",
        )
    ]
    assert files(folder) == {**UNSORTED, **STAYING}
    assert _no_batch(data_dir)
    assert _plan(window) == PLAN


def test_the_confirmed_batch_is_carried_out_and_named(
    qtbot: QtBot, window: Window, folder: Path, data_dir: Path
) -> None:
    # [0014.23]
    page = window.organize
    _planned(qtbot, window)
    page.move_button.click()
    assert window.tasks.holding() is not None  # it acts: closing waits for it
    wait_idle(qtbot, window)
    assert _lines(window) == [f"Moved 3 files, 15 B in {folder} (batch 1)."]
    assert files(folder) == {**SORTED, **STAYING}
    assert page.summary.text() == ""
    assert _plan(window) == NO_PLAN
    assert (page.state.text(), page.bar.isVisible()) == ("", False)
    assert not page.move_button.isEnabled()
    assert _batches(window) == [_batch(data_dir, 1, "3 files moved · Sorted · Done")]


def test_only_the_confirmed_moves_the_plan_still_holds_are_carried_out(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path
) -> None:
    # [0014.14] While the dialog was open, b.pdf changed and d.png came: neither moves.
    _planned(qtbot, window)
    dialogs.meanwhile += [
        lambda: write(folder / B, b"b.pdf, longer"),
        lambda: write(folder / "d.png", b"d.png"),
    ]
    window.organize.move_button.click()
    wait_idle(qtbot, window)
    assert _lines(window) == [
        f"Moved 2 files, 10 B in {folder} (batch 1).",
        f"Changed since the plan: {folder / B}",
    ]
    assert files(folder) == {
        f"Images/{A}": b"a.jpg",
        f"Audio/{C}": b"c.mp3",
        B: b"b.pdf, longer",
        "d.png": b"d.png",
        **STAYING,
    }


def test_when_nothing_confirmed_still_holds_nothing_moves(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path, data_dir: Path
) -> None:
    # [0014.14]
    _planned(qtbot, window)
    changed = {name: f"{name}, changed".encode() for name in (A, B, C)}
    dialogs.meanwhile += [
        functools.partial(write, folder / name, data) for name, data in changed.items()
    ]
    window.organize.move_button.click()
    wait_idle(qtbot, window)
    assert _lines(window) == [
        f"Nothing was moved in {folder}.",
        f"Changed since the plan: {folder / A}",
        f"Changed since the plan: {folder / C}",
        f"Changed since the plan: {folder / B}",
    ]
    assert files(folder) == {**changed, **STAYING}
    assert _no_batch(data_dir)


def test_a_folder_refused_when_planned_again_moves_nothing(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path, data_dir: Path
) -> None:
    # [0014.14] It became a project while the dialog was open.
    _planned(qtbot, window)
    dialogs.meanwhile.append(lambda: write(folder / "Makefile", b"all:"))
    window.organize.move_button.click()
    wait_idle(qtbot, window)
    assert _lines(window) == [f"Refused: {folder}: A project: Makefile"]
    assert files(folder) == {**UNSORTED, **STAYING, "Makefile": b"all:"}
    assert _no_batch(data_dir)


def test_a_file_refused_at_move_time_stays(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs, folder: Path
) -> None:
    # [0014.14] Checked again right before the batch (preflight, 0004): a program holds it.
    held = FakeOpenFiles(open_paths=[folder / C])
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs, open_files=held)
    _planned(qtbot, window)
    window.organize.move_button.click()
    wait_idle(qtbot, window)
    assert _lines(window) == [
        f"Moved 2 files, 10 B in {folder} (batch 1).",
        f"Refused: {folder / C} (In use by a program)",
    ]
    assert files(folder) == {
        f"Images/{A}": b"a.jpg",
        f"Documents/{B}": b"b.pdf",
        C: b"c.mp3",
        **STAYING,
    }


def test_a_batch_that_stops_says_what_is_still_sorted(
    qtbot: QtBot,
    window: Window,
    folder: Path,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0014.23] c.mp3 cannot be moved, and a.jpg, moved before it, cannot be moved back.
    faults = FlakyRename({folder / C: "before", folder / "Images" / A: "before"})
    monkeypatch.setattr(sessions, "renamer", renaming(faults))
    _planned(qtbot, window)
    window.organize.move_button.click()
    wait_idle(qtbot, window)
    assert _lines(window) == [
        f"Stopped: [Errno 13] refused before the move: '{folder / C}'. Batch 1: Failed.",
        f"Still sorted: {folder / 'Images' / A}",
        "Undo batch 1 moves them back.",
    ]
    assert files(folder) == {f"Images/{A}": b"a.jpg", B: b"b.pdf", C: b"c.mp3", **STAYING}
    assert _batches(window) == [_batch(data_dir, 1, "1 file moved · Sorted · Failed")]


def test_a_batch_rolled_back_has_nothing_still_sorted(
    qtbot: QtBot, window: Window, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0014.23]
    faults = FlakyRename({folder / C: "before"})
    monkeypatch.setattr(sessions, "renamer", renaming(faults))
    _planned(qtbot, window)
    window.organize.move_button.click()
    wait_idle(qtbot, window)
    assert _lines(window) == [
        f"Stopped: [Errno 13] refused before the move: '{folder / C}'. Batch 1: Rolled back.",
    ]
    assert files(folder) == {**UNSORTED, **STAYING}


def test_unfinished_work_of_another_domain_comes_first(
    qtbot: QtBot, window: Window, data_dir: Path, folder: Path
) -> None:
    # [0014.23] The batches are still listed, as `organize list` lists them.
    pending_quarantine(data_dir)
    _opened(qtbot, window)
    _planned(qtbot, window)
    assert _lines(window) == [
        "Unfinished work (Quarantine) comes first: nothing was changed. Use Recover."
    ]
    assert _plan(window) == NO_PLAN
    assert files(folder) == {**UNSORTED, **STAYING}


# --- the batches [0014.23] -----------------------------------------------------------------------


def test_the_batches_are_read_each_time_the_page_opens(
    qtbot: QtBot, window: Window, tmp_path: Path, zone: Path, data_dir: Path, folder: Path
) -> None:
    # [0014.23] [0014.52] Sorted by the CLI while the window was open.
    page = window.organize
    assert _batches(window) == []
    assert page.no_batches.text() == "No batches yet."
    assert not page.batches.isVisible()
    assert not page.undo_button.isEnabled()
    window.show_page("overview")
    assert (
        run(["organize", "move", str(folder), "--yes"], scan_context(tmp_path, zone, data_dir))[0]
        == 0
    )
    _opened(qtbot, window)
    assert _batches(window) == [_batch(data_dir, 1, "3 files moved · Sorted · Done")]
    assert (page.no_batches.isVisible(), page.batches.isVisible()) == (False, True)
    page.batches.setCurrentItem(page.batch_row(1))
    assert page.undo_button.text() == "Undo…"
    assert page.undo_button.isEnabled()


# --- undo [0014.14] [0014.23] --------------------------------------------------------------------


def test_undo_shows_its_plan_then_moves_back_after_confirmation(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path, data_dir: Path
) -> None:
    # [0014.23]
    _sorted(qtbot, window, dialogs)
    _undo(qtbot, window, 1)
    assert dialogs.asked == [
        Confirmation(
            title="Undo batch 1",
            text=f"Move back 3 files (15 B) sorted by batch 1 in {folder}?",
            details=("Images/a.jpg → a.jpg", "Audio/c.mp3 → c.mp3", "Documents/b.pdf → b.pdf"),
            action="Move back",
        )
    ]
    assert _lines(window) == [f"Moved back 3 files, 15 B in {folder} (batch 2, undoing batch 1)."]
    assert files(folder) == {**UNSORTED, **STAYING}
    assert _batches(window) == [
        _batch(data_dir, 2, "3 files moved · Undo of batch 1 · Done"),
        _batch(data_dir, 1, "3 files moved · Sorted · Done, undone"),
    ]


def test_an_undo_cancelled_moves_nothing_back(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path
) -> None:
    # [0014.3] [0014.23]
    _sorted(qtbot, window, dialogs)
    dialogs.answer = False
    _undo(qtbot, window, 1)
    assert len(dialogs.asked) == 1
    assert files(folder) == {**SORTED, **STAYING}
    assert [row.data(0, Qt.ItemDataRole.UserRole) for row in _rows(window.organize.batches)] == [1]


def test_what_cannot_move_back_stays_and_is_shown(
    qtbot: QtBot,
    window: Window,
    dialogs: FakeDialogs,
    folder: Path,
    tmp_path: Path,
    data_dir: Path,
) -> None:
    # [0014.23] a.jpg was taken out of the folder: the batch is partly undone.
    _sorted(qtbot, window, dialogs)
    (folder / "Images" / A).rename(tmp_path / A)
    _undo(qtbot, window, 1)
    assert dialogs.asked[0].details == (
        "Audio/c.mp3 → c.mp3",
        "Documents/b.pdf → b.pdf",
        "Images/a.jpg (No longer there)",
    )
    assert files(folder) == {B: b"b.pdf", C: b"c.mp3", **STAYING}
    assert _batches(window)[1] == _batch(
        data_dir, 1, "3 files moved · Sorted · Done, partly undone"
    )


def test_an_undo_with_nothing_to_move_back_says_so(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path, tmp_path: Path
) -> None:
    # [0014.23]
    _sorted(qtbot, window, dialogs)
    for path in SORTED:
        (folder / path).rename(tmp_path / Path(path).name)
    _undo(qtbot, window, 1)
    assert dialogs.asked == []
    assert _lines(window) == [
        "Nothing to move back from batch 1.",
        "Images/a.jpg (No longer there)",
        "Audio/c.mp3 (No longer there)",
        "Documents/b.pdf (No longer there)",
    ]


def test_an_undo_batch_cannot_be_undone(qtbot: QtBot, window: Window, dialogs: FakeDialogs) -> None:
    # [0014.23]
    _sorted(qtbot, window, dialogs)
    _undo(qtbot, window, 1)
    dialogs.asked.clear()
    _undo(qtbot, window, 2)
    assert dialogs.asked == []
    assert _lines(window) == ["Refused: batch 2: An undo cannot be undone"]


def test_an_undo_moves_back_only_what_its_plan_still_holds(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path
) -> None:
    # [0014.14] a.jpg changed while the dialog was open.
    _sorted(qtbot, window, dialogs)
    dialogs.meanwhile.append(lambda: write(folder / "Images" / A, b"a.jpg, edited"))
    _undo(qtbot, window, 1)
    assert _lines(window) == [
        f"Moved back 2 files, 10 B in {folder} (batch 2, undoing batch 1).",
        f"Changed since the plan: {folder / 'Images' / A}",
    ]
    assert files(folder) == {f"Images/{A}": b"a.jpg, edited", B: b"b.pdf", C: b"c.mp3", **STAYING}


def test_an_undo_where_nothing_still_holds_moves_nothing_back(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path, data_dir: Path
) -> None:
    # [0014.14]
    _sorted(qtbot, window, dialogs)
    dialogs.meanwhile += [functools.partial(write, folder / path, b"edited") for path in SORTED]
    _undo(qtbot, window, 1)
    assert _lines(window) == [
        "Nothing was moved back from batch 1.",
        f"Changed since the plan: {folder / 'Images' / A}",
        f"Changed since the plan: {folder / 'Audio' / C}",
        f"Changed since the plan: {folder / 'Documents' / B}",
    ]
    assert query(data_dir, "SELECT COUNT(*) FROM move_batches") == [(1,)]


def test_an_undo_that_stops_names_what_takes_the_rest(
    qtbot: QtBot,
    window: Window,
    dialogs: FakeDialogs,
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0014.23]
    _sorted(qtbot, window, dialogs)
    source = folder / "Audio" / C
    faults = FlakyRename({source: "before"})
    monkeypatch.setattr(sessions, "renamer", renaming(faults))
    _undo(qtbot, window, 1)
    assert _lines(window) == [
        f"Stopped: [Errno 13] refused before the move: '{source}'. Batch 2: Rolled back.",
        "Undo batch 1 again to move back the files still sorted.",
    ]
    assert files(folder) == {**SORTED, **STAYING}


def test_sort_and_undo_rename_as_the_contexts_system_does(
    qtbot: QtBot,
    window: Window,
    dialogs: FakeDialogs,
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0017.3] the window's batches take organize.platforms.renamer(platform) too
    asked: list[Platform] = []

    def recorded(platform: Platform) -> Rename:
        asked.append(platform)
        return os.rename

    monkeypatch.setattr(sessions, "renamer", recorded)
    _sorted(qtbot, window, dialogs)
    _undo(qtbot, window, 1)
    assert asked == ["linux", "linux"]
    assert files(folder) == {A: b"a.jpg", B: b"b.pdf", C: b"c.mp3", **STAYING}


# --- in Russian [0014.23] [0014.44] --------------------------------------------------------------


def test_the_page_in_russian(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    folder: Path,
) -> None:
    # [0014.23] [0014.44] [0014.52] A card names its category in Russian and its directory
    # beside it; every path keeps the directory's name on disk.
    window = make_window(
        qtbot, environment(tmp_path, zone, data_dir), language="ru", dialogs=dialogs
    )
    _opened(qtbot, window)
    page, ru = window.organize, window.translator
    assert page.choose_button.text() == "Выбрать папку…"
    assert (page.folder.accessibleName(), page.folder.placeholderText()) == (
        "Папка",
        "Папка не выбрана",
    )
    assert page.no_batches.text() == "Пакетов пока нет."
    assert page.recent_title.text() == "Последние пакеты"
    _planned(qtbot, window)
    assert page.choose_button.text() == "Изменить…"
    assert page.state.text() == (
        f"План составлен {moment(_planned_at(page))} · ничего ещё не перемещено"
    )
    assert _plan(window) == (
        [
            ("Images", "1 файл · 5 Б", "Изображения (папка Images)", "a.jpg"),
            ("Audio", "1 файл · 5 Б", "Аудио (папка Audio)", "c.mp3"),
            ("Documents", "1 файл · 5 Б", "Документы (папка Documents)", "b.pdf"),
        ],
        [
            ("old", ru.label(StayReason.NOT_REGULAR)),
            (".hidden", "Служебный файл папки"),
            ("old.tmp", f"{ru.label(StayReason.JUNK)}: temp-files"),
        ],
    )
    assert (page.stays_title.text(), page.stays_note.text()) == (
        "Остаются на месте",
        "3 файла, каждый — по своей причине",
    )
    assert page.will.text() == "Будет разложено: 3 файла по 3 папкам."
    assert page.safe.text() == (
        "Ничего не переименовывается, не перезаписывается и не удаляется; пакет можно вернуть."
    )
    assert page.move_button.text() == "Разложить…"
    page.move_button.click()
    wait_idle(qtbot, window)
    [asked] = dialogs.asked
    assert (asked.title, asked.action) == ("Разложить файлы", "Разложить файлы")
    assert asked.details == ("a.jpg → Images/", "c.mp3 → Audio/", "b.pdf → Documents/")
    assert _lines(window) == [f"Перемещено: 3 файла, 15 Б, папка {folder} (пакет 1)."]
    assert files(folder) == {**SORTED, **STAYING}
    assert _batches(window) == [
        (
            f"Пакет 1 · {_when(data_dir, 1)}",
            "3 файла · Сортировка · Готово",
        )
    ]
    assert page.undo_button.text() == "Вернуть файлы…"
    dialogs.asked.clear()
    _undo(qtbot, window, 1)
    [asked] = dialogs.asked
    assert asked.details == (
        "Images/a.jpg → a.jpg",
        "Audio/c.mp3 → c.mp3",
        "Documents/b.pdf → b.pdf",
    )
    assert files(folder) == {**UNSORTED, **STAYING}


def _planned_at(page: OrganizePage) -> float:
    planned = page.planned_at
    assert planned is not None
    return planned


# --- the look [0014.52] --------------------------------------------------------------------------


def test_the_folder_is_a_field_from_the_home_folder_then_change_and_the_plan_s_state(
    qtbot: QtBot, window: Window, folder: Path, home: Path
) -> None:
    # [0014.52]
    page = window.organize
    field = page.folder
    assert isinstance(field, Field)
    assert (field.accessibleName(), field.placeholderText(), field.text()) == (
        "Folder",
        "No folder chosen",
        "",
    )
    assert field.isReadOnly()
    assert not field.mark.icon().isNull()
    assert page.state.text() == ""
    before = time.time()
    _planned(qtbot, window)
    planned = _planned_at(page)
    assert before <= planned <= time.time()
    assert field.text() == str(Path("~") / "zone" / "Downloads")
    assert page.choose_button.text() == "Change…"
    assert page.state.text() == f"Plan made {moment(planned)} · nothing moved yet"
    assert page.state.property("role") == "caption"
    assert page.state.geometry().right() > page.choose_button.geometry().right() + 100  # at right


def test_a_refused_folder_is_shown_in_the_field_too(
    qtbot: QtBot, window: Window, folder: Path, home: Path
) -> None:
    # [0014.52]
    write(folder / "Makefile", b"all:")
    _planned(qtbot, window)
    page = window.organize
    assert (page.folder.text(), page.choose_button.text()) == ("~/zone/Downloads", "Change…")
    assert page.state.text() == ""


def test_a_card_per_category_three_to_a_row_each_with_its_icon_files_size_name_and_names(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, zone: Path
) -> None:
    # [0014.52] Four categories: two rows, the second's free places kept, so that every card
    # is as wide; a card names its first three files.
    mixed = zone / "Mixed"
    for name in ("1.jpg", "2.jpg", "3.png", "4.gif", "b.pdf", "c.mp3", "d.zip"):
        write(mixed / name, b"12345")
    dialogs.folders = [mixed]
    _planned(qtbot, window)
    page = window.organize
    assert _cards(window) == [
        ("Images", "4 files · 20 B", "Images", "1.jpg, 2.jpg, 3.png"),
        ("Audio", "1 file · 5 B", "Audio", "c.mp3"),
        ("Documents", "1 file · 5 B", "Documents", "b.pdf"),
        ("Archives", "1 file · 5 B", "Archives", "d.zip"),
    ]
    assert [card.icon.name for card in page.cards] == ["image", "music", "file-text", "archive"]
    grid = page.categories
    assert [_at(grid, 0, 0), _at(grid, 0, 1), _at(grid, 0, 2), _at(grid, 1, 0)] == page.cards
    assert grid.count() == 6  # two free places at the end of the second row
    widths = [card.width() for card in page.cards]
    assert max(widths) - min(widths) <= 1  # the grid's remainder
    card = page.cards[0]
    assert card.property("role") == "card"
    assert (card.name.property("role"), card.amount.property("role")) == ("card-title", "secondary")
    assert card.names.property("role") == "secondary"
    assert card.icon.colours() == (LIGHT.text, LIGHT.surface2)
    assert card.amount.geometry().right() > card.icon.geometry().right() + 100  # at right
    assert card.icon.geometry().bottom() < card.name.geometry().top() < card.names.geometry().top()


@pytest.mark.parametrize(
    ("category", "icon"),
    [
        ("Images", "image"),
        ("Videos", "square-play"),
        ("Audio", "music"),
        ("Documents", "file-text"),
        ("Archives", "archive"),
        ("Installers", "download"),
        ("Fonts", "folder"),
    ],
)
def test_each_category_has_its_icon(category: str, icon: str) -> None:
    # [0014.52] A category the table names otherwise has the folder icon.
    assert CATEGORY_ICONS.get(category, "folder") == icon


def test_what_stays_a_row_per_file_its_reason_at_the_right_the_detail_under_the_list(
    qtbot: QtBot, window: Window, folder: Path
) -> None:
    # [0014.52]
    _planned(qtbot, window)
    page = window.organize
    assert page.staying.isVisible()
    assert (page.stays_title.text(), page.stays_note.text()) == (
        "Stays in place",
        "3 files, each with its reason",
    )
    assert page.stays_title.property("role") == "strong"
    assert page.stays.accessibleName() == "Stays in place"
    assert page.stays.isHeaderHidden()
    [row, *_] = _rows(page.stays)
    assert row.textAlignment(1) == int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    assert row.data(1, QUIET)
    assert not page.detail.isVisible()
    assert not page.explain.isVisible()
    page.stays.setCurrentItem(_rows(page.stays)[2])
    assert page.detail.text().splitlines() == [
        f"Path: {folder / 'old.tmp'}",
        "Stays: Junk: for the cleanup: temp-files",
    ]
    assert page.explain.isVisible()
    assert page.stays.geometry().bottom() < page.detail.geometry().top()
    assert page.detail.geometry().bottom() < page.explain.geometry().top()
    page.stays.setCurrentIndex(QModelIndex())
    assert (page.detail.isVisible(), page.explain.isVisible()) == (False, False)


def test_the_recent_batches_in_a_card_at_the_right_each_with_its_folder_in_its_tooltip(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path, home: Path
) -> None:
    # [0014.52]
    _sorted(qtbot, window, dialogs)
    page = window.organize
    recent = page.recent
    assert recent.property("role") == "card"
    assert recent.width() == BATCHES_WIDTH
    assert (page.recent_title.text(), page.recent_title.property("role")) == (
        "Recent batches",
        "caption",
    )
    assert page.batches.accessibleName() == "Recent batches"
    [row] = _rows(page.batches)
    assert row.toolTip(0) == "~/zone/Downloads"
    assert row.data(0, Qt.ItemDataRole.UserRole) == 1
    assert page.undo_button.parent() is recent


def test_the_cards_and_the_batches_scroll_with_the_page_and_the_bar_is_at_the_bottom(
    qtbot: QtBot, window: Window, folder: Path
) -> None:
    # [0014.52]
    _planned(qtbot, window)
    page = window.organize
    assert page.area.widget() is page.controls
    assert page.area.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    layout = page.layout()
    assert layout is not None
    last = layout.itemAt(layout.count() - 1)
    assert last is not None
    assert last.widget() is page.bar
    assert page.bar.property("role") == "bar"
    assert page.bar.isVisible()
    assert (page.will.property("role"), page.safe.property("role")) == ("strong", "secondary")
    assert page.safe.text() == (
        "Nothing is renamed, overwritten or deleted; the batch can be undone."
    )
    assert page.move_button.property("role") == "primary"
    assert page.will.geometry().right() < page.safe.geometry().left()
    assert page.safe.geometry().right() < page.move_button.geometry().left()
    assert page.head.geometry().bottom() < page.area.geometry().top()
    cards = page.cards[0].mapTo(page, page.cards[0].rect().topLeft())
    staying = page.staying.mapTo(page, page.staying.rect().topLeft())
    recent = page.recent.mapTo(page, page.recent.rect().topLeft())
    assert cards.y() < staying.y()
    assert staying.x() < recent.x()
    assert page.folder.mapTo(page, page.folder.rect().topLeft()).y() < cards.y()


def test_one_category_or_two_keep_the_cards_as_wide_as_three_to_a_row(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, zone: Path
) -> None:
    # [0014.52]
    two = zone / "Two"
    write(two / "a.jpg", b"a")
    write(two / "b.pdf", b"b")
    dialogs.folders = [two]
    _planned(qtbot, window)
    page = window.organize
    grid = page.categories
    assert grid.count() == 3
    [card, *_] = page.cards
    assert card.width() * 3 < page.controls.width()
