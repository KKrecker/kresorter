"""The Findings page: the head, groups, chips, search, the detail and the bar with the
selection; Review never preselected; quarantine from the findings (decision 0014, items 4, 20,
21 and 49)."""

import functools
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem
from pytestqt.qtbot import QtBot

from fakes import UnreliableOpenFiles
from safeclean.analysis.score import Level
from safeclean.quarantine.service import QuarantineService
from safeclean.ui import sessions
from safeclean.ui.findings import (
    DETAIL_WIDTH,
    PATH,
    SEARCH_WIDTHS,
    FindingDetail,
    folders,
    found_in,
)
from safeclean.ui.i18n import Translator
from safeclean.ui.parts import BADGE, EMPHASIS, QUIET, SECONDARY
from safeclean.ui.window import Window
from support.files import write
from support.journal import pending_move_batch, query
from support.window import FakeDialogs, environment, junk_tree, make_window, scanned, wait_idle


@pytest.fixture
def tree(zone: Path) -> dict[str, Path]:
    return junk_tree(zone)


@pytest.fixture
def dialogs() -> FakeDialogs:
    return FakeDialogs()


@pytest.fixture
def window(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    home: Path,
    tree: dict[str, Path],
    dialogs: FakeDialogs,
) -> Window:
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), dialogs=dialogs)
    scanned(qtbot, window)
    return window


def _groups(window: Window) -> list[QTreeWidgetItem]:
    return _children(window.findings.tree.invisibleRootItem())


def _children(group: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    children = []
    for index in range(group.childCount()):
        child = group.child(index)
        assert child is not None
        children.append(child)
    return children


def _shown(window: Window) -> list[str]:
    """The paths shown, group by group."""
    return [
        child.data(0, PATH)
        for group in _groups(window)
        if not group.isHidden()
        for child in _children(group)
        if not child.isHidden()
    ]


def _checked(window: Window) -> set[Path]:
    return {finding.entry.path for finding in window.findings.selected()}


def _check(window: Window, path: Path, on: bool = True) -> None:
    state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
    window.findings.item(path).setCheckState(0, state)


def _check_group(group: QTreeWidgetItem, on: bool = True) -> None:
    group.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)


# --- the findings [0014.20] [0014.49] ------------------------------------------------------------


def _row(item: QTreeWidgetItem) -> tuple[str, str | None, str, str]:
    """A row's name, what is under it, its size and its level."""
    return (item.text(0), item.data(0, SECONDARY), item.text(1), item.text(2))


def test_findings_are_grouped_by_their_strongest_reason_with_files_rules_and_size(
    window: Window, tmp_path: Path, tree: dict[str, Path]
) -> None:
    # [0014.20] [0014.49] Under a group's reason its files and, for junk, its rules; for
    # duplicate copies, that one copy of each stays.
    assert [_row(group) for group in _groups(window)] == [
        ("Cache", "4 files · python-bytecode", "31 B", "Safe"),
        ("Duplicate copy", "1 file · one copy of each stays", "10 B", "Likely safe"),
        ("Not changed for a long time", "1 file", "10 B", "Review"),
    ]
    cache, copies, old = _groups(window)
    assert [group.data(2, BADGE) for group in (cache, copies, old)] == [
        "safe",
        "likely_safe",
        "review",
    ]
    assert all(group.data(0, EMPHASIS) and group.data(1, EMPHASIS) for group in _groups(window))
    assert [_row(child) for child in _children(cache)] == [
        (tree[name].name, str(Path("~", tree[name].parent.relative_to(tmp_path))), size, "")
        for name, size in (("n", "15 B"), ("m", "8 B"), ("kept", "4 B"), ("copy", "4 B"))
    ]
    assert [child.data(0, PATH) for child in _children(cache)] == [
        str(tree[name]) for name in ("n", "m", "kept", "copy")
    ]
    assert all(child.data(1, QUIET) for child in _children(cache))
    assert [_row(child) for child in _children(copies)] == [
        ("img.jpg", str(Path("~", "zone", "backup")), "10 B", "")
    ]
    header = window.findings.tree.headerItem()
    assert [header.text(column) for column in range(3)] == ["Name", "Size", "Level"]
    right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    assert header.textAlignment(1) == right
    assert cache.textAlignment(1) == right
    assert _children(cache)[0].textAlignment(1) == right


def test_a_folder_elsewhere_is_shown_as_it_is(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.49]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    scanned(qtbot, window)
    [old] = _children(_groups(window)[2])
    assert old.data(0, SECONDARY) == str(tree["old"].parent)


def test_the_head_says_which_folders_were_scanned_and_when_with_rescan(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, home: Path, tree: dict[str, Path]
) -> None:
    # [0014.49]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    page = window.findings
    assert page.head.subtitle.text() == "What the last scan found, grouped by its strongest reason."
    assert page.head.controls == (page.rescan_button,)
    assert page.rescan_button.text() == "Rescan"
    scanned(qtbot, window)
    found = window.overview.scanned
    assert found is not None
    assert found.roots == [zone]
    assert page.head.subtitle.text() == f"Scan of {Path('~', 'zone')}, {_moment(found.at)}"
    write(zone / "c" / "__pycache__" / "y.pyc", b"more")
    page.rescan_button.click()
    wait_idle(qtbot, window)
    rescanned = window.overview.scanned
    assert rescanned is not None
    assert rescanned is not found
    assert _row(_groups(window)[0]) == ("Cache", "5 files · python-bytecode", "35 B", "Safe")


def test_the_folders_of_a_scan_and_the_scanned_folder_a_file_is_in(
    tmp_path: Path, home: Path
) -> None:
    # [0014.49] "and" before the last; the deepest scanned folder that holds the file.
    en, ru = Translator("en"), Translator("ru")
    a, b, c = tmp_path / "a", tmp_path / "a" / "b", Path("/elsewhere")
    assert folders(en, []) == ""
    assert folders(en, [a]) == str(Path("~", "a"))
    assert folders(en, [a, c]) == f"{Path('~', 'a')} and {c}"
    assert folders(en, [a, b, c]) == f"{Path('~', 'a')}, {Path('~', 'a', 'b')} and {c}"
    assert folders(ru, [a, c]) == f"{Path('~', 'a')} и {c}"
    assert found_in(b / "f.txt", [a, b]) == b
    assert found_in(b / "f.txt", [b, a]) == b
    assert found_in(a / "f.txt", [a, b]) == a
    assert found_in(c / "f.txt", [a, b]) == c


def test_a_chip_per_level_with_its_count_and_the_search_with_its_icon(
    qtbot: QtBot, window: Window
) -> None:
    # [0014.49] The search is as wide as it may be when the chips leave it the room.
    page = window.findings
    assert [box.text() for box in page.filters.values()] == ["Safe 4", "Likely safe 1", "Review 1"]
    assert all(box.isCheckable() for box in page.filters.values())
    assert page.search.placeholderText() == "Search the paths"
    assert page.search.accessibleName() == "Search the paths"
    assert not page.search.mark.icon().isNull()
    assert page.search.minimumWidth() == SEARCH_WIDTHS[0] == 160
    assert page.search.maximumWidth() == SEARCH_WIDTHS[1] == 240
    window.resize(1200, 780)
    window.show_page("findings")
    qtbot.waitUntil(lambda: page.search.width() == 240)


def test_the_level_filters_are_all_on_at_first_and_hide_their_findings(
    window: Window, tree: dict[str, Path]
) -> None:
    # [0014.20]
    filters = window.findings.filters
    assert list(filters) == list(Level)
    assert all(box.isChecked() for box in filters.values())
    assert len(_shown(window)) == 6
    filters[Level.SAFE].setChecked(False)
    assert _shown(window) == [str(tree["backup"]), str(tree["old"])]
    assert _groups(window)[0].isHidden()
    filters[Level.REVIEW].setChecked(False)
    assert _shown(window) == [str(tree["backup"])]
    filters[Level.SAFE].setChecked(True)
    filters[Level.REVIEW].setChecked(True)
    assert len(_shown(window)) == 6


def test_the_search_keeps_the_paths_that_contain_the_text_ignoring_case(
    window: Window, tree: dict[str, Path]
) -> None:
    # [0014.20]
    window.findings.search.setText("IMG.JPG")
    assert _shown(window) == [str(tree["backup"])]
    assert [group.isHidden() for group in _groups(window)] == [True, False, True]
    window.findings.search.setText("x.PYC")
    assert _shown(window) == [str(tree["kept"]), str(tree["copy"])]
    window.findings.filters[Level.SAFE].setChecked(False)
    assert _shown(window) == []
    window.findings.search.setText("")
    window.findings.filters[Level.SAFE].setChecked(True)
    assert len(_shown(window)) == 6


def _moment(at: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(at))


def _facts(detail: FindingDetail) -> dict[str, tuple[str, str]]:
    return {
        fact: (detail.labels[fact].text(), shown.text()) for fact, shown in detail.facts.items()
    }


def test_the_detail_shows_level_name_folder_size_time_where_found_and_every_reason(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, home: Path, tree: dict[str, Path]
) -> None:
    # [0014.20] [0014.49]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    scanned(qtbot, window)
    page = window.findings
    detail = page.detail
    assert detail.width() == DETAIL_WIDTH == 320
    assert detail.property("role") == "side"
    assert detail.none.text() == "Choose a file to see why it was found."
    assert not detail.none.isHidden()
    assert detail.content.isHidden()

    page.tree.setCurrentItem(page.item(tree["copy"]))
    assert detail.none.isHidden()
    assert not detail.content.isHidden()
    assert (detail.badge.text(), detail.badge.property("badge")) == ("Safe", "safe")
    assert detail.name.text() == "x.pyc"
    assert detail.folder.text() == str(Path("~", "zone", "b", "__pycache__"))
    assert _facts(detail) == {
        "size": ("Size", "4 B"),
        "modified": ("Modified", _moment(tree["copy"].stat().st_mtime_ns / 1e9)),
        "found": ("Found in", str(Path("~", "zone"))),
    }
    assert detail.why_title.text() == "Why"
    assert detail.why.text().splitlines() == [
        "Cache: python-bytecode",
        f"Duplicate copy: {tree['kept']}",
    ]
    page.tree.setCurrentItem(page.item(tree["kept"]))
    assert detail.why.text().splitlines() == [
        "Cache: python-bytecode",
        "This copy stays: the others are its duplicates.",
    ]
    page.tree.setCurrentItem(page.item(tree["backup"]))
    assert (detail.badge.text(), detail.badge.property("badge")) == ("Likely safe", "likely_safe")
    page.tree.setCurrentItem(page.item(tree["old"]))
    assert detail.why.text() == "Not changed for a long time: unmodified for 800 days"
    page.tree.setCurrentItem(_groups(window)[0])
    assert not detail.none.isHidden()
    assert detail.content.isHidden()


def test_the_detail_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.49]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), language="ru")
    scanned(qtbot, window)
    detail = window.findings.detail
    assert detail.none.text() == "Выберите файл, чтобы увидеть, почему он найден."
    window.findings.tree.setCurrentItem(window.findings.item(tree["old"]))
    assert detail.badge.text() == "Проверить"
    assert [label.text() for label in detail.labels.values()] == ["Размер", "Изменён", "Найден в"]
    assert detail.why_title.text() == "Почему"


def _bar(window: Window) -> tuple[str, str]:
    return (window.findings.chosen.text(), window.findings.chosen_size.text())


def test_the_bar_shows_the_selection_and_moving_needs_one(
    window: Window, tree: dict[str, Path]
) -> None:
    # [0014.20] [0014.49]
    page = window.findings
    assert page.bar.property("role") == "bar"
    assert _bar(window) == ("3 files selected", "· 27 B")
    assert page.move_button.text() == "Move to quarantine…"
    assert page.move_button.property("role") == "primary"
    assert page.move_button.isEnabled()
    page.clear_button.click()
    assert _bar(window) == ("0 files selected", "· 0 B")
    assert not page.move_button.isEnabled()
    _check(window, tree["old"])
    assert _bar(window) == ("1 file selected", "· 10 B")
    assert page.move_button.isEnabled()


def test_the_page_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.20] [0014.49]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), language="ru")
    scanned(qtbot, window)
    page = window.findings
    assert [_row(group) for group in _groups(window)] == [
        ("Кэш", "4 файла · python-bytecode", "31 Б", "Безопасно"),
        ("Копия дубликата", "1 файл · одна копия каждого остаётся", "10 Б", "Скорее безопасно"),
        ("Давно не изменялся", "1 файл", "10 Б", "Проверить"),
    ]
    header = page.tree.headerItem()
    assert [header.text(column) for column in range(3)] == ["Имя", "Размер", "Уровень"]
    assert [box.text() for box in page.filters.values()] == [
        "Безопасно 4",
        "Скорее безопасно 1",
        "Проверить 1",
    ]
    assert page.rescan_button.text() == "Сканировать снова"
    assert _bar(window) == ("Выбрано: 3 файла", "· 27 Б")
    assert page.move_button.text() == "Переместить в карантин…"


# --- review is never preselected [0014.4] --------------------------------------------------------


def test_the_safe_findings_are_selected_and_the_others_are_not(
    window: Window, tree: dict[str, Path]
) -> None:
    # [0014.4] The kept copy is Safe junk, but the analysis does not propose it.
    assert _checked(window) == {tree["m"], tree["n"], tree["copy"]}
    kept = window.findings.item(tree["kept"])
    assert not kept.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert kept.data(0, Qt.ItemDataRole.CheckStateRole) is None


def test_selecting_a_level_selects_only_what_the_analysis_proposes(
    window: Window, tree: dict[str, Path]
) -> None:
    # [0014.4] There is no way to select the whole Review level.
    page = window.findings
    assert list(page.select_buttons) == [Level.SAFE, Level.LIKELY_SAFE]
    assert [button.text() for button in page.select_buttons.values()] == [
        "Select all: Safe",
        "Select all: Likely safe",
    ]
    page.clear_button.click()
    page.select_buttons[Level.LIKELY_SAFE].click()
    assert _checked(window) == {tree["backup"]}
    page.select_buttons[Level.SAFE].click()
    assert _checked(window) == {tree["m"], tree["n"], tree["copy"], tree["backup"]}


def test_selecting_a_level_takes_only_the_findings_shown(
    window: Window, tree: dict[str, Path]
) -> None:
    # [0014.4]
    page = window.findings
    page.clear_button.click()
    page.search.setText("proj")
    page.select_buttons[Level.SAFE].click()
    assert _checked(window) == {tree["m"]}


def test_selecting_a_group_selects_only_what_the_analysis_proposes(
    window: Window, tree: dict[str, Path]
) -> None:
    # [0014.4]
    cache, copies, old = _groups(window)
    window.findings.clear_button.click()
    assert [group.checkState(0) for group in (cache, copies, old)] == [Qt.CheckState.Unchecked] * 3
    _check_group(old)
    assert _checked(window) == set()
    assert old.checkState(0) == Qt.CheckState.Unchecked
    _check_group(cache)
    assert _checked(window) == {tree["m"], tree["n"], tree["copy"]}
    assert cache.checkState(0) == Qt.CheckState.Checked
    _check(window, tree["n"], on=False)
    assert cache.checkState(0) == Qt.CheckState.PartiallyChecked
    _check_group(cache, on=False)
    assert _checked(window) == set()
    _check_group(copies)
    assert _checked(window) == {tree["backup"]}


def test_a_review_finding_is_selected_by_its_own_check_box_alone(
    window: Window, tree: dict[str, Path]
) -> None:
    # [0014.4]
    _, _, old = _groups(window)
    _check(window, tree["old"])
    assert tree["old"] in _checked(window)
    assert old.checkState(0) == Qt.CheckState.Checked
    _check_group(old, on=False)
    assert tree["old"] not in _checked(window)


# --- quarantine from the findings [0014.21] ------------------------------------------------------


def test_moving_asks_first_and_a_cancel_moves_nothing(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.3] [0014.21]
    dialogs = FakeDialogs(confirm=False)
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), dialogs=dialogs)
    scanned(qtbot, window)
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    [asked] = dialogs.asked
    assert asked.title == "Move to quarantine"
    assert asked.text == (
        "Move 3 files (27 B) to the quarantine? They can be restored from the Quarantine page."
    )
    assert asked.details == tuple(str(tree[name]) for name in ("n", "m", "copy"))
    assert asked.action == "Move to quarantine"
    assert not asked.danger
    assert all(path.exists() for path in tree.values())
    assert not data_dir.exists()
    assert window.findings.result.text() == ""


def test_the_confirmed_findings_move_and_leave_the_list(
    qtbot: QtBot, window: Window, tree: dict[str, Path], data_dir: Path
) -> None:
    # [0014.21]
    page = window.findings
    page.move_button.click()
    assert window.tasks.holding() is not None  # it acts: closing waits for it
    wait_idle(qtbot, window)
    assert page.result.text() == "Moved to the quarantine: 3 files, 27 B"
    assert not any(tree[name].exists() for name in ("m", "n", "copy"))
    assert query(data_dir, "SELECT original_path FROM items ORDER BY id") == [
        (str(tree[name]),) for name in ("n", "m", "copy")
    ]
    assert _shown(window) == [str(tree["kept"]), str(tree["backup"]), str(tree["old"])]
    assert [_row(group) for group in _groups(window)] == [
        ("Cache", "1 file · python-bytecode", "4 B", "Safe"),
        ("Duplicate copy", "1 file · one copy of each stays", "10 B", "Likely safe"),
        ("Not changed for a long time", "1 file", "10 B", "Review"),
    ]
    assert [box.text() for box in page.filters.values()] == ["Safe 1", "Likely safe 1", "Review 1"]
    assert _bar(window) == ("0 files selected", "· 0 B")
    assert not page.move_button.isEnabled()


def test_the_selection_the_user_made_is_kept_for_what_stays(
    qtbot: QtBot, window: Window, tree: dict[str, Path]
) -> None:
    # [0014.21]
    window.findings.clear_button.click()
    _check(window, tree["m"])
    _check(window, tree["old"])
    write(tree["old"], b"changed since the scan")  # refused at move time: it stays listed
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    assert window.findings.result.text().splitlines() == [
        "Moved to the quarantine: 1 file, 8 B",
        f"Refused: {tree['old']} (Changed since the scan)",
    ]
    assert _checked(window) == {tree["old"]}
    assert not tree["m"].exists()
    assert tree["old"].exists()


def test_a_refusal_says_what_it_found(qtbot: QtBot, window: Window, tree: dict[str, Path]) -> None:
    # [0014.14] [0014.21] The copy that stays changed since the scan: the other copy stays.
    window.findings.clear_button.click()
    _check(window, tree["copy"])
    write(tree["kept"], b"changed")
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    assert window.findings.result.text().splitlines() == [
        "Moved to the quarantine: 0 files, 0 B",
        f"Refused: {tree['copy']} (The copy that stays has changed: {tree['kept']})",
    ]
    assert _checked(window) == {tree["copy"]}


def test_a_finding_changed_while_the_dialog_was_open_stays(
    qtbot: QtBot, window: Window, dialogs: FakeDialogs, tree: dict[str, Path]
) -> None:
    # [0014.14] Each confirmed file is checked again when it moves.
    window.findings.clear_button.click()
    _check(window, tree["m"])
    _check(window, tree["n"])
    dialogs.meanwhile.append(lambda: write(tree["m"], b"changed bytecode"))
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    assert window.findings.result.text().splitlines() == [
        "Moved to the quarantine: 1 file, 15 B",
        f"Refused: {tree['m']} (Changed since the scan)",
    ]
    assert tree["m"].read_bytes() == b"changed bytecode"
    assert not tree["n"].exists()


def test_a_group_whose_findings_all_moved_leaves_the_list(
    qtbot: QtBot, window: Window, tree: dict[str, Path]
) -> None:
    # [0014.21]
    window.findings.clear_button.click()
    _check(window, tree["backup"])
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    assert [_row(group) for group in _groups(window)] == [
        ("Cache", "4 files · python-bytecode", "31 B", "Safe"),
        ("Not changed for a long time", "1 file", "10 B", "Review"),
    ]
    assert not tree["backup"].exists()


def test_a_batch_stopped_by_an_error_puts_back_what_had_moved(
    qtbot: QtBot, window: Window, tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0014.21]
    moves: list[Path] = []

    def second_fails(source: Path, target: Path) -> None:
        moves.append(source)
        if len(moves) == 2:
            raise OSError(5, "I/O error")
        source.replace(target)

    service = functools.partial(QuarantineService, move=second_fails)
    monkeypatch.setattr(sessions, "QuarantineService", service)
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    assert window.findings.result.text().splitlines() == [
        "Moved to the quarantine: 0 files, 0 B",
        "Stopped: [Errno 5] I/O error. The files that had moved were put back.",
    ]
    assert all(path.exists() for path in tree.values())
    assert len(_shown(window)) == 6


def test_unfinished_work_of_another_domain_comes_first(
    qtbot: QtBot, window: Window, tree: dict[str, Path], data_dir: Path
) -> None:
    pending_move_batch(data_dir)
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    assert window.findings.result.text() == (
        "Unfinished work (Organize) comes first: nothing was changed. Use Recover."
    )
    assert all(path.exists() for path in tree.values())
    assert query(data_dir, "SELECT COUNT(*) FROM operations") == [(0,)]


def test_without_a_reliable_open_file_check_nothing_moves(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.21]
    unreliable = environment(tmp_path, zone, data_dir, open_files=UnreliableOpenFiles())
    window = make_window(qtbot, unreliable)
    scanned(qtbot, window)
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    assert window.findings.result.text() == (
        "No reliable open-file check on this system: nothing was moved."
    )
    assert all(path.exists() for path in tree.values())


def test_a_session_that_cannot_run_says_why(
    qtbot: QtBot, tmp_path: Path, zone: Path, tree: dict[str, Path]
) -> None:
    # [0014.21] The data directory inside a scan zone (0009).
    inside = zone / "data"
    window = make_window(qtbot, environment(tmp_path, zone, inside))
    scanned(qtbot, window)
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    assert window.findings.result.text() == (
        f"The data folder cannot be used here: data directory {inside} is inside scan zone {zone}"
    )
    assert all(path.exists() for path in tree.values())
