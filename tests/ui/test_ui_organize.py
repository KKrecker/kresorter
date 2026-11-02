"""The Organize page: where organize does not move files, why, and nothing else; elsewhere a
folder's plan, the batch carried out after confirmation and named, the batches and their undo
(decision 0014, items 14 and 23). The plan is made again inside the session: only the confirmed
moves it still holds unchanged are carried out, and what no longer holds is reported."""

import functools
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
from pytestqt.qtbot import QtBot

from fakes import FakeOpenFiles, UnreliableOpenFiles
from safeclean.core.heuristics import Platform
from safeclean.core.open_files import OpenFileChecker
from safeclean.organize.mover import carry_out
from safeclean.organize.planner import StayReason
from safeclean.ui import sessions
from safeclean.ui.dialogs import Confirmation
from safeclean.ui.window import Window
from support.cli import run, scan_context
from support.files import write
from support.journal import pending_quarantine, query
from support.moves import A, B, C, FlakyRename, files, three_files
from support.window import FakeDialogs, environment, make_window, wait_idle

UNSORTED = {A: b"a.jpg", B: b"b.pdf", C: b"c.mp3"}
SORTED = {f"Images/{A}": b"a.jpg", f"Documents/{B}": b"b.pdf", f"Audio/{C}": b"c.mp3"}
STAYING = {"old/inside.jpg": b"inside", ".hidden": b"hidden", "old.tmp": b"old"}
STAYS = [
    "old (Not a regular file)",
    ".hidden (The folder's own file)",
    "old.tmp (Junk: for the cleanup: temp-files)",
]
PLAN = [
    ("Images: 1 file, 5 B", ["a.jpg → Images/"]),
    ("Audio: 1 file, 5 B", ["c.mp3 → Audio/"]),
    ("Documents: 1 file, 5 B", ["b.pdf → Documents/"]),
    ("Stay in place: 3", STAYS),
]


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


def _child(item: QTreeWidgetItem, index: int) -> QTreeWidgetItem:
    child = item.child(index)
    assert child is not None
    return child


def _tree(tree: QTreeWidget) -> list[tuple[str, list[str]]]:
    """Each group of ``tree``, with the texts of its items."""
    root = tree.invisibleRootItem()
    groups = [_child(root, index) for index in range(root.childCount())]
    return [
        (group.text(0), [_child(group, index).text(0) for index in range(group.childCount())])
        for group in groups
    ]


def _batches(window: Window) -> list[list[str]]:
    tree = window.organize.batches
    root = tree.invisibleRootItem()
    rows = [_child(root, index) for index in range(root.childCount())]
    return [[row.text(column) for column in range(tree.columnCount())] for row in rows]


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
    # [0014.23]
    page = window.organize
    assert not page.blocked.isVisible()
    assert page.controls.isVisible()
    assert page.choose_button.text() == "Choose folder…"
    assert not page.move_button.isEnabled()
    _planned(qtbot, window)
    assert page.summary.text() == f"Would move 3 files, 15 B in {folder}."
    assert _tree(page.plan) == PLAN
    assert page.move_button.text() == "Move files"
    assert page.move_button.isEnabled()
    assert files(folder) == {**UNSORTED, **STAYING}
    assert _no_batch(data_dir)


def test_a_folder_where_every_file_moves_has_nothing_that_stays(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, zone: Path
) -> None:
    # [0014.23]
    plain = three_files(zone / "Plain")
    dialogs.folders = [plain]
    _planned(qtbot, window)
    assert window.organize.summary.text() == f"Would move 3 files, 15 B in {plain}."
    assert _tree(window.organize.plan) == PLAN[:3]


def test_a_folder_with_nothing_to_move_says_so(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, zone: Path
) -> None:
    # [0014.23]
    quiet = zone / "Quiet"
    write(quiet / ".hidden", b"hidden")
    dialogs.folders = [quiet]
    _planned(qtbot, window)
    page = window.organize
    assert page.summary.text() == f"Nothing to move in {quiet}."
    assert _tree(page.plan) == [("Stay in place: 1", [".hidden (The folder's own file)"])]
    assert not page.move_button.isEnabled()


def test_a_refused_folder_is_planned_nothing(qtbot: QtBot, window: Window, folder: Path) -> None:
    # [0014.23] A folder organize does not sort (0012 item 8).
    write(folder / "Makefile", b"all:")
    _planned(qtbot, window)
    page = window.organize
    assert page.summary.text() == f"Refused: {folder}: A project: Makefile"
    assert _tree(page.plan) == []
    assert not page.move_button.isEnabled()


def test_a_folder_dialog_closed_plans_nothing(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs
) -> None:
    # [0014.23]
    dialogs.folders = [None]
    _planned(qtbot, window)
    assert window.organize.summary.text() == ""
    assert _tree(window.organize.plan) == []


def test_a_plan_made_again_replaces_the_one_shown(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path, zone: Path
) -> None:
    # [0014.23]
    quiet = zone / "Quiet"
    write(quiet / ".hidden", b"hidden")
    dialogs.folders = [folder, quiet]
    _planned(qtbot, window)
    _planned(qtbot, window)
    assert _tree(window.organize.plan) == [
        ("Stay in place: 1", [".hidden (The folder's own file)"])
    ]
    assert not window.organize.move_button.isEnabled()


# --- the batch [0014.14] [0014.23] ---------------------------------------------------------------


def test_moving_asks_first_and_a_cancel_moves_nothing(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path, data_dir: Path
) -> None:
    # [0014.23]
    _planned(qtbot, window)
    dialogs.answer = False
    window.organize.move_button.click()
    wait_idle(qtbot, window)
    assert dialogs.asked == [
        Confirmation(
            title="Move files",
            text=f"Move 3 files (15 B) into category folders in {folder}? Undo moves them back.",
            details=("a.jpg → Images/", "c.mp3 → Audio/", "b.pdf → Documents/"),
            action="Move files",
        )
    ]
    assert files(folder) == {**UNSORTED, **STAYING}
    assert _no_batch(data_dir)
    assert _tree(window.organize.plan) == PLAN


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
    assert _tree(page.plan) == []
    assert not page.move_button.isEnabled()
    assert _batches(window) == [["1", _when(data_dir, 1), "Sorted", "3", "Done", str(folder)]]


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
    monkeypatch.setattr(sessions, "carry_out", functools.partial(carry_out, rename=faults))
    _planned(qtbot, window)
    window.organize.move_button.click()
    wait_idle(qtbot, window)
    assert _lines(window) == [
        f"Stopped: [Errno 13] refused before the move: '{folder / C}'. Batch 1: Failed.",
        f"Still sorted: {folder / 'Images' / A}",
        "Undo batch 1 moves them back.",
    ]
    assert files(folder) == {f"Images/{A}": b"a.jpg", B: b"b.pdf", C: b"c.mp3", **STAYING}
    assert _batches(window) == [["1", _when(data_dir, 1), "Sorted", "1", "Failed", str(folder)]]


def test_a_batch_rolled_back_has_nothing_still_sorted(
    qtbot: QtBot, window: Window, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0014.23]
    faults = FlakyRename({folder / C: "before"})
    monkeypatch.setattr(sessions, "carry_out", functools.partial(carry_out, rename=faults))
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
    assert _tree(window.organize.plan) == []
    assert files(folder) == {**UNSORTED, **STAYING}


# --- the batches [0014.23] -----------------------------------------------------------------------


def test_the_batches_are_read_each_time_the_page_opens(
    qtbot: QtBot, window: Window, tmp_path: Path, zone: Path, data_dir: Path, folder: Path
) -> None:
    # [0014.23] Sorted by the CLI while the window was open.
    page = window.organize
    header = page.batches.headerItem()
    assert [header.text(column) for column in range(6)] == [
        "Id",
        "Time",
        "Kind",
        "Files moved",
        "State",
        "Folder",
    ]
    assert _batches(window) == []
    assert not page.undo_button.isEnabled()
    window.show_page("overview")
    assert (
        run(["organize", "move", str(folder), "--yes"], scan_context(tmp_path, zone, data_dir))[0]
        == 0
    )
    _opened(qtbot, window)
    assert _batches(window) == [["1", _when(data_dir, 1), "Sorted", "3", "Done", str(folder)]]
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
        ["2", _when(data_dir, 2), "Undo of batch 1", "3", "Done", str(folder)],
        ["1", _when(data_dir, 1), "Sorted", "3", "Done, undone", str(folder)],
    ]


def test_an_undo_cancelled_moves_nothing_back(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path
) -> None:
    # [0014.23]
    _sorted(qtbot, window, dialogs)
    dialogs.answer = False
    _undo(qtbot, window, 1)
    assert len(dialogs.asked) == 1
    assert files(folder) == {**SORTED, **STAYING}
    assert [row[0] for row in _batches(window)] == ["1"]


def test_what_cannot_move_back_stays_and_is_shown(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, folder: Path, tmp_path: Path
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
    assert _batches(window)[1][4] == "Done, partly undone"


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
    monkeypatch.setattr(sessions, "carry_out", functools.partial(carry_out, rename=faults))
    _undo(qtbot, window, 1)
    assert _lines(window) == [
        f"Stopped: [Errno 13] refused before the move: '{source}'. Batch 2: Rolled back.",
        "Undo batch 1 again to move back the files still sorted.",
    ]
    assert files(folder) == {**SORTED, **STAYING}


# --- in Russian [0014.23] ------------------------------------------------------------------------


def test_the_page_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs, folder: Path
) -> None:
    # [0014.23]
    window = make_window(
        qtbot, environment(tmp_path, zone, data_dir), language="ru", dialogs=dialogs
    )
    _opened(qtbot, window)
    page, ru = window.organize, window.translator
    assert page.choose_button.text() == "Выбрать папку…"
    _planned(qtbot, window)
    assert page.summary.text() == f"Папка {folder}: будет перемещено 3 файла, 15 Б."
    assert _tree(page.plan) == [
        ("Images: 1 файл, 5 Б", ["a.jpg → Images/"]),
        ("Audio: 1 файл, 5 Б", ["c.mp3 → Audio/"]),
        ("Documents: 1 файл, 5 Б", ["b.pdf → Documents/"]),
        (
            "Остаются на месте: 3",
            [
                f"old ({ru.label(StayReason.NOT_REGULAR)})",
                ".hidden (Служебный файл папки)",
                f"old.tmp ({ru.label(StayReason.JUNK)}: temp-files)",
            ],
        ),
    ]
    assert page.move_button.text() == "Переместить файлы"
    page.move_button.click()
    wait_idle(qtbot, window)
    assert _lines(window) == [f"Перемещено: 3 файла, 15 Б, папка {folder} (пакет 1)."]
    assert _batches(window) == [["1", _when(data_dir, 1), "Сортировка", "3", "Готово", str(folder)]]
    assert page.undo_button.text() == "Вернуть файлы…"
