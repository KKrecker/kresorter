"""The Overview page: the folders to scan, Scan, and what it found (decision 0014, item 19)."""

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from fakes import UnreliableOpenFiles
from safeclean.analysis.score import Level
from safeclean.ui.window import Window
from support.files import write
from support.window import FakeDialogs, environment, junk_tree, make_window, scanned


@pytest.fixture
def tree(zone: Path) -> dict[str, Path]:
    return junk_tree(zone)


def _folders(window: Window) -> list[str]:
    folders = window.overview.folders
    return [folders.item(row).text() for row in range(folders.count())]


def _summary(window: Window) -> list[str]:
    page = window.overview
    return [label.text() for label in (*page.levels.values(), page.duplicates, page.skipped)]


# --- the folders to scan [0014.19] ---------------------------------------------------------------


def test_the_folders_are_the_safe_zones_at_first(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.19]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    assert _folders(window) == [str(zone)]
    assert window.overview.roots() == [zone]
    assert window.overview.summary.isHidden()
    assert window.overview.state.text() == "Not scanned yet."


def test_folders_the_user_adds_can_be_removed_again(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.19] A safe zone stays; a folder added twice is listed once; a dialog closed adds none.
    extra, other = tmp_path / "extra", tmp_path / "other"
    extra.mkdir()
    other.mkdir()
    dialogs = FakeDialogs(folders=[extra, None, extra, other])
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), dialogs=dialogs)
    page = window.overview
    for _ in range(4):
        page.add_button.click()
    assert _folders(window) == [str(zone), str(extra), str(other)]
    assert dialogs.folders == []

    assert not page.remove_button.isEnabled()
    page.folders.setCurrentRow(0)  # the safe zone
    assert not page.remove_button.isEnabled()
    page.folders.setCurrentRow(1)
    assert page.remove_button.isEnabled()
    page.remove_button.click()
    assert _folders(window) == [str(zone), str(other)]
    assert page.roots() == [zone, other]


# --- Scan [0014.19] ------------------------------------------------------------------------------


def test_scan_shows_each_level_the_duplicate_groups_and_the_skipped_paths(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.19] With the default thresholds: 800 days unchanged is old.
    (zone / "link").symlink_to(tree["notes"])
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    scanned(qtbot, window)
    page = window.overview
    assert not page.summary.isHidden()
    assert page.state.text() == ""
    assert list(page.levels) == list(Level)
    assert _summary(window) == [
        "Safe: 4 files, 31 B",
        "Likely safe: 1 file, 10 B",
        "Review: 1 file, 10 B",
        "Duplicate groups: 2",
        "Skipped paths: 1",
    ]
    assert [page.levels[level].property("badge") for level in Level] == [
        level.value for level in Level
    ]
    assert page.unreliable.isHidden()
    assert len(window.findings.findings()) == 6


def test_scan_takes_the_folders_added(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.19]
    extra = tmp_path / "extra"
    write(extra / "__pycache__" / "e.cpython-313.pyc", b"extra")
    dialogs = FakeDialogs(folders=[extra])
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), dialogs=dialogs)
    window.overview.add_button.click()
    scanned(qtbot, window)
    assert _summary(window)[0] == "Safe: 5 files, 36 B"


def test_without_a_reliable_open_file_check_the_page_says_so(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.19]
    unreliable = environment(tmp_path, zone, data_dir, open_files=UnreliableOpenFiles())
    window = make_window(qtbot, unreliable)
    scanned(qtbot, window)
    page = window.overview
    assert not page.unreliable.isHidden()
    assert page.unreliable.text() == (
        "Files in use cannot be recognized on this system, so nothing can be moved to the"
        " quarantine."
    )


def test_the_summary_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.19]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), language="ru")
    assert window.overview.state.text() == "Сканирования ещё не было."
    scanned(qtbot, window)
    assert _summary(window) == [
        "Безопасно: 4 файла, 31 Б",
        "Скорее безопасно: 1 файл, 10 Б",
        "Проверить: 1 файл, 10 Б",
        "Групп дубликатов: 2",
        "Пропущено путей: 0",
    ]
