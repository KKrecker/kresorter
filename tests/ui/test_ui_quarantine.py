"""The Quarantine page: the quarantined files from the journal, a row each, the bar with the
selection, Restore, and Delete permanently, the one action drawn in the danger colour (decision
0014, items 5, 22 and 51)."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem, QWidget
from pytestqt.qtbot import QtBot

from fakes import UnreliableOpenFiles
from kresorter.ui.dialogs import Confirmation
from kresorter.ui.parts import QUIET, SECONDARY
from kresorter.ui.window import Window
from support.cli import run
from support.files import write
from support.journal import query
from support.window import (
    FakeDialogs,
    children,
    environment,
    junk_tree,
    make_window,
    scanned,
    wait_idle,
)


@pytest.fixture
def tree(zone: Path) -> dict[str, Path]:
    return junk_tree(zone)


@pytest.fixture
def dialogs() -> FakeDialogs:
    return FakeDialogs()


def _opened(qtbot: QtBot, window: Window) -> None:
    window.show_page("quarantine")
    wait_idle(qtbot, window)


def _refreshed(qtbot: QtBot, window: Window) -> None:
    window.quarantine.refresh_button.click()
    wait_idle(qtbot, window)


def _moved(qtbot: QtBot, window: Window) -> None:
    """Scan and move what is selected at first: n, m and copy, items 1, 2 and 3."""
    scanned(qtbot, window)
    window.findings.move_button.click()
    wait_idle(qtbot, window)


@pytest.fixture
def window(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    tree: dict[str, Path],
    dialogs: FakeDialogs,
) -> Window:
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), dialogs=dialogs)
    _moved(qtbot, window)
    dialogs.asked.clear()
    _opened(qtbot, window)
    return window


def _listed(window: Window) -> list[QTreeWidgetItem]:
    return children(window.quarantine.items.invisibleRootItem())


def _rows(window: Window) -> list[tuple[str, str, str]]:
    """Each row's id, original path (its folder, then its name) and size."""
    return [
        (row.text(2), str(Path(row.data(0, SECONDARY), row.text(0))), row.text(1))
        for row in _listed(window)
    ]


def _bar(window: Window) -> tuple[str, str]:
    return (window.quarantine.chosen.text(), window.quarantine.chosen_size.text())


def _ids(window: Window) -> list[str]:
    return [row[0] for row in _rows(window)]


def _check(window: Window, *item_ids: int) -> None:
    for item_id in item_ids:
        window.quarantine.row(item_id).setCheckState(0, Qt.CheckState.Checked)


def _states(data_dir: Path) -> list[tuple[object, ...]]:
    return list(query(data_dir, "SELECT id, state FROM items ORDER BY id"))


# --- the list [0014.22] [0014.51] ---------------------------------------------------------------


def test_the_page_lists_the_quarantined_files_by_id(window: Window, tree: dict[str, Path]) -> None:
    # [0014.22]
    page = window.quarantine
    assert _rows(window) == [
        ("1", str(tree["n"]), "15 B"),
        ("2", str(tree["m"]), "8 B"),
        ("3", str(tree["copy"]), "4 B"),
    ]
    assert page.total.text() == "In the quarantine: 3 files, 27 B"
    assert page.selected() == []
    assert not page.restore_button.isEnabled()
    assert not page.purge_button.isEnabled()
    _check(window, 2)
    assert page.selected() == [2]
    assert page.restore_button.isEnabled()
    assert page.purge_button.isEnabled()


def test_a_row_has_the_name_its_original_folder_the_size_and_the_id_in_secondary_text(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, home: Path, tree: dict[str, Path]
) -> None:
    # [0014.51]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    _moved(qtbot, window)
    _opened(qtbot, window)
    page = window.quarantine
    header = page.items.headerItem()
    assert [header.text(column) for column in range(3)] == ["Name", "Size", "ID"]
    first = _listed(window)[0]
    assert (first.text(0), first.data(0, SECONDARY)) == (
        "n.cpython-313.pyc",
        str(Path("~", "zone", "lib", "__pycache__")),
    )
    assert (first.text(1), first.text(2)) == ("15 B", "1")
    assert [first.data(column, QUIET) for column in (1, 2)] == [True, True]
    right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    assert header.textAlignment(1) == first.textAlignment(1) == right
    assert not page.items.isHidden()
    assert page.empty.isHidden()


def test_with_no_file_the_page_says_the_quarantine_is_empty(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.51]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    _opened(qtbot, window)
    page = window.quarantine
    assert page.empty.text() == "The quarantine is empty."
    assert page.empty.property("role") == "secondary"
    assert page.items.isHidden()
    assert page.total.isHidden()
    _moved(qtbot, window)
    _refreshed(qtbot, window)
    assert page.empty.isHidden()
    assert not page.items.isHidden()


def test_the_bar_shows_the_files_checked_and_their_size_with_restore_and_delete(
    window: Window,
) -> None:
    # [0014.51]
    page = window.quarantine
    assert page.bar.property("role") == "bar"
    assert _bar(window) == ("0 files selected", "· 0 B")
    _check(window, 1, 3)
    assert _bar(window) == ("2 files selected", "· 19 B")
    assert page.restore_button.property("role") == "primary"
    assert page.purge_button.property("role") == "danger"
    for part in (page.chosen, page.restore_button, page.permanent, page.purge_button):
        assert page.bar.isAncestorOf(part)


def test_the_list_is_read_again_each_time_the_page_opens(
    qtbot: QtBot, window: Window, tree: dict[str, Path]
) -> None:
    # [0014.22]
    window.show_page("findings")
    window.findings.item(tree["backup"]).setCheckState(0, Qt.CheckState.Checked)
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    _opened(qtbot, window)
    assert _rows(window)[-1] == ("4", str(tree["backup"]), "10 B")
    assert window.quarantine.total.text() == "In the quarantine: 4 files, 37 B"


def test_refresh_reads_what_another_session_changed(
    qtbot: QtBot, window: Window, tree: dict[str, Path]
) -> None:
    # [0014.22]
    code, _, _ = run(["quarantine", "restore", "2"], window.environment.scan_context())
    assert code == 0
    assert _ids(window) == ["1", "2", "3"]
    window.quarantine.refresh_button.click()
    wait_idle(qtbot, window)
    assert _ids(window) == ["1", "3"]


def test_without_a_reliable_open_file_check_the_page_says_so(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.22] As `quarantine list`: no session without a reliable open-file check.
    unreliable = environment(tmp_path, zone, data_dir, open_files=UnreliableOpenFiles())
    window = make_window(qtbot, unreliable)
    _opened(qtbot, window)
    assert window.quarantine.result.text() == (
        "No reliable open-file check on this system: the quarantine cannot be used."
    )
    assert _rows(window) == []


def test_the_page_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.22] [0014.51]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), language="ru")
    _opened(qtbot, window)
    page = window.quarantine
    assert page.empty.text() == "Карантин пуст."
    _moved(qtbot, window)
    _refreshed(qtbot, window)
    header = page.items.headerItem()
    assert [header.text(column) for column in range(3)] == ["Имя", "Размер", "№"]
    assert page.total.text() == "Сейчас в карантине: 3 файла, 27 Б"
    assert _bar(window) == ("Выбрано: 0 файлов", "· 0 Б")
    assert [b.text() for b in (page.refresh_button, page.restore_button, page.purge_button)] == [
        "Обновить",
        "Восстановить",
        "Удалить навсегда",
    ]


# --- restore [0014.22] ---------------------------------------------------------------------------


def test_restoring_asks_first_and_a_cancel_restores_nothing(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, tree: dict[str, Path], data_dir: Path
) -> None:
    # [0014.3] [0014.22]
    dialogs.answer = False
    _check(window, 1, 3)
    window.quarantine.restore_button.click()
    wait_idle(qtbot, window)
    assert dialogs.asked == [
        Confirmation(
            title="Restore",
            text="Restore 2 files (19 B) to where they were?",
            details=(str(tree["n"]), str(tree["copy"])),
            action="Restore",
        )
    ]
    assert not tree["n"].exists()
    assert _states(data_dir) == [(1, "quarantined"), (2, "quarantined"), (3, "quarantined")]
    assert window.quarantine.result.text() == ""


def test_the_confirmed_files_are_restored_and_leave_the_list(
    qtbot: QtBot, window: Window, tree: dict[str, Path], data_dir: Path
) -> None:
    # [0014.22]
    _check(window, 1, 3)
    window.quarantine.restore_button.click()
    assert window.tasks.holding() is not None
    wait_idle(qtbot, window)
    assert window.quarantine.result.text() == "Restored: 2 files"
    assert tree["n"].read_bytes() == b"other bytecode!"
    assert tree["copy"].read_bytes() == b"same"
    assert _rows(window) == [("2", str(tree["m"]), "8 B")]
    assert window.quarantine.total.text() == "In the quarantine: 1 file, 8 B"
    assert _states(data_dir) == [(1, "restored"), (2, "quarantined"), (3, "restored")]


def test_a_refused_restore_says_why_and_stays_selected(
    qtbot: QtBot, window: Window, tree: dict[str, Path]
) -> None:
    # [0014.22] Something is in its place now: it is never written over.
    write(tree["n"], b"a new file")
    _check(window, 1)
    window.quarantine.restore_button.click()
    wait_idle(qtbot, window)
    assert window.quarantine.result.text().splitlines() == [
        "Restored: 0 files",
        f"Refused: [1] {tree['n']} (Its place is taken: {tree['n']})",
    ]
    assert tree["n"].read_bytes() == b"a new file"
    assert window.quarantine.selected() == [1]


def test_a_restore_acts_only_on_what_is_still_in_the_quarantine(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, tree: dict[str, Path], data_dir: Path
) -> None:
    # [0014.14] Restored by another session while the dialog was open.
    scan = window.environment.scan_context()
    dialogs.meanwhile.append(lambda: run(["quarantine", "restore", "1"], scan))
    _check(window, 1, 2)
    window.quarantine.restore_button.click()
    wait_idle(qtbot, window)
    assert window.quarantine.result.text().splitlines() == [
        "Restored: 1 file",
        f"Refused: [1] {tree['n']} (Not in the quarantine: restored)",
    ]
    assert _states(data_dir) == [(1, "restored"), (2, "restored"), (3, "quarantined")]
    assert _ids(window) == ["3"]


# --- delete permanently [0014.5] [0014.22] -------------------------------------------------------


def test_deleting_shows_its_plan_first_and_a_cancel_deletes_nothing(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, tree: dict[str, Path], data_dir: Path
) -> None:
    # [0014.3] [0014.5] [0014.22]
    dialogs.answer = False
    _check(window, 1, 2)
    window.quarantine.purge_button.click()
    wait_idle(qtbot, window)
    assert dialogs.asked == [
        Confirmation(
            title="Delete permanently",
            text="Delete 2 files (23 B) permanently? They cannot be restored.",
            details=(str(tree["n"]), str(tree["m"])),
            action="Delete permanently",
            danger=True,
        )
    ]
    assert _states(data_dir) == [(1, "quarantined"), (2, "quarantined"), (3, "quarantined")]
    assert _ids(window) == ["1", "2", "3"]


def test_the_confirmed_files_are_deleted_and_the_space_freed(
    qtbot: QtBot, window: Window, tree: dict[str, Path], data_dir: Path
) -> None:
    # [0014.22]
    _check(window, 1, 2)
    window.quarantine.purge_button.click()
    wait_idle(qtbot, window)
    assert window.quarantine.result.text() == "Deleted permanently: 2 files, freed 23 B"
    assert _rows(window) == [("3", str(tree["copy"]), "4 B")]
    assert _states(data_dir) == [(1, "purged"), (2, "purged"), (3, "quarantined")]
    assert not tree["n"].exists()


def test_a_copy_changed_in_the_quarantine_is_not_deleted(
    qtbot: QtBot, window: Window, tree: dict[str, Path], data_dir: Path
) -> None:
    # [0014.22]
    [(vault,)] = query(data_dir, "SELECT vault_path FROM items WHERE id = 1")
    write(Path(str(vault)), b"changed in the vault")
    _check(window, 1)
    window.quarantine.purge_button.click()
    wait_idle(qtbot, window)
    assert window.quarantine.result.text().splitlines() == [
        "Deleted permanently: 0 files, freed 0 B",
        f"Refused: [1] {tree['n']} (Its copy in the quarantine has changed: {vault})",
    ]
    assert Path(str(vault)).read_bytes() == b"changed in the vault"
    assert _ids(window) == ["2", "3"]


def test_a_deletion_acts_only_on_what_its_plan_still_holds(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, tree: dict[str, Path], data_dir: Path
) -> None:
    # [0014.14] Restored by another session while the plan was shown: the plan is made again.
    scan = window.environment.scan_context()
    dialogs.meanwhile.append(lambda: run(["quarantine", "restore", "1"], scan))
    _check(window, 1, 2)
    window.quarantine.purge_button.click()
    wait_idle(qtbot, window)
    assert window.quarantine.result.text().splitlines() == [
        "Deleted permanently: 1 file, freed 8 B",
        f"Refused: [1] {tree['n']} (Not in the quarantine: restored)",
    ]
    assert _states(data_dir) == [(1, "restored"), (2, "purged"), (3, "quarantined")]
    assert tree["n"].read_bytes() == b"other bytecode!"


def test_nothing_left_to_delete_asks_nothing(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, tree: dict[str, Path]
) -> None:
    # [0014.22] Restored by another session since the list was read.
    run(["quarantine", "restore", "1"], window.environment.scan_context())
    _check(window, 1)
    window.quarantine.purge_button.click()
    wait_idle(qtbot, window)
    assert dialogs.asked == []
    assert window.quarantine.result.text().splitlines() == [
        "Nothing to delete.",
        f"Refused: [1] {tree['n']} (Not in the quarantine: restored)",
    ]
    assert _ids(window) == ["2", "3"]
    assert tree["n"].exists()


def test_only_deleting_permanently_is_drawn_as_danger(window: Window) -> None:
    # [0014.5] Its button and its badge, and nothing else in the window.
    page = window.quarantine
    danger = {
        widget
        for widget in window.findChildren(QWidget)
        if "danger" in (widget.property("role"), widget.property("badge"))
    }
    assert danger == {page.purge_button, page.permanent}
    assert page.purge_button.text() == "Delete permanently"
    assert page.permanent.text() == "Cannot be undone"


# --- select all [0018.5] -------------------------------------------------------------------------


def test_select_all_checks_every_row_and_clear_unchecks_them(window: Window) -> None:
    # [0018.5] Beside the files checked, in the bar.
    page = window.quarantine
    assert page.select_all_button.text() == "Select all"
    assert page.clear_button.text() == "Clear selection"
    for part in (page.select_all_button, page.clear_button):
        assert page.bar.isAncestorOf(part)
    page.select_all_button.click()
    assert page.selected() == [1, 2, 3]
    assert _bar(window) == ("3 files selected", "· 27 B")
    assert page.restore_button.isEnabled()
    assert page.purge_button.isEnabled()
    page.clear_button.click()
    assert page.selected() == []
    assert _bar(window) == ("0 files selected", "· 0 B")
    assert not page.restore_button.isEnabled()


def test_select_all_then_restore_asks_for_every_file(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, tree: dict[str, Path], data_dir: Path
) -> None:
    # [0018.5] The confirmation of before, for every file.
    window.quarantine.select_all_button.click()
    window.quarantine.restore_button.click()
    wait_idle(qtbot, window)
    (asked,) = dialogs.asked
    assert asked.text == "Restore 3 files (27 B) to where they were?"
    assert window.quarantine.result.text() == "Restored: 3 files"
    assert _states(data_dir) == [(1, "restored"), (2, "restored"), (3, "restored")]


def test_select_all_and_clear_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0018.5]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), language="ru")
    _opened(qtbot, window)
    page = window.quarantine
    assert (page.select_all_button.text(), page.clear_button.text()) == (
        "Выбрать все",
        "Снять выбор",
    )
