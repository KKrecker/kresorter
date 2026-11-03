"""The Overview page: the scan card with the folders as chips, what the last scan found a card
per level, and a card each for Quarantine, Organize and Autostart (decision 0014, items 19
and 48)."""

import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from fakes import UnreliableOpenFiles
from kresorter.analysis.score import Level
from kresorter.ui.overview import FolderChip
from kresorter.ui.shown import shown_path
from kresorter.ui.window import Window
from support.files import write
from support.moves import three_files
from support.window import FakeDialogs, environment, junk_tree, make_window, scanned, wait_idle


@pytest.fixture
def tree(zone: Path) -> dict[str, Path]:
    return junk_tree(zone)


def _chips(window: Window) -> list[FolderChip]:
    return window.overview.chips()


def _folders(window: Window) -> list[Path]:
    return [chip.path for chip in _chips(window)]


def _moment(at: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(at))


# --- the folders to scan [0014.19] [0014.48] -----------------------------------------------------


def test_a_folder_is_shown_from_the_home_folder_as_tilde(tmp_path: Path) -> None:
    # [0014.48]
    home = tmp_path / "home"
    assert shown_path(home, home) == "~"
    assert shown_path(home / ".cache", home) == str(Path("~") / ".cache")
    assert shown_path(home / "a" / "b", home) == str(Path("~") / "a" / "b")
    assert shown_path(tmp_path / "elsewhere", home) == str(tmp_path / "elsewhere")
    assert shown_path(tmp_path / "homework", home) == str(tmp_path / "homework")


def test_the_folders_are_the_safe_zones_at_first(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, home: Path
) -> None:
    # [0014.19] [0014.48] A chip each: the folder icon and the path, a safe zone without a
    # remove button.
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    page = window.overview
    assert _folders(window) == [zone]
    assert page.roots() == [zone]
    [chip] = _chips(window)
    assert chip.icon.name == "folder"
    assert chip.label.text() == str(Path("~") / "zone")
    assert chip.toolTip() == str(zone)
    assert chip.remove is None
    assert chip.property("role") == "chip"
    assert page.add_button.text() == "Add folder"
    assert page.add_button.property("role") == "plain"
    assert page.level_cards.isHidden()
    assert page.last.text() == "Not scanned yet."


def test_folders_the_user_adds_can_be_removed_again(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, home: Path
) -> None:
    # [0014.19] [0014.48] A safe zone stays; a folder added twice is listed once; a dialog
    # closed adds none; an added folder's chip has a remove button.
    extra, other = tmp_path / "extra", tmp_path / "other"
    extra.mkdir()
    other.mkdir()
    dialogs = FakeDialogs(folders=[extra, None, extra, other])
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), dialogs=dialogs)
    page = window.overview
    for _ in range(4):
        page.add_button.click()
    assert _folders(window) == [zone, extra, other]
    assert dialogs.folders == []

    zone_chip, extra_chip, other_chip = _chips(window)
    assert zone_chip.remove is None
    assert extra_chip.remove is not None
    assert extra_chip.remove.accessibleName() == f"Remove folder {Path('~') / 'extra'}"
    assert extra_chip.remove.toolTip() == extra_chip.remove.accessibleName()
    assert other_chip.remove is not None
    extra_chip.remove.click()
    assert _folders(window) == [zone, other]
    assert page.roots() == [zone, other]
    assert extra_chip.parent() is None or not extra_chip.isVisible()


def test_the_chips_sit_in_one_row_with_add_folder_at_their_end(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.48]
    extra = tmp_path / "extra"
    extra.mkdir()
    window = make_window(
        qtbot, environment(tmp_path, zone, data_dir), dialogs=FakeDialogs(folders=[extra])
    )
    page = window.overview
    page.add_button.click()
    first, second = _chips(window)
    qtbot.waitUntil(lambda: second.isVisible())
    assert first.geometry().top() == second.geometry().top()
    assert second.geometry().left() > first.geometry().right()
    assert page.add_button.mapTo(page, page.add_button.rect().topLeft()).x() > (
        second.mapTo(page, second.rect().topRight()).x()
    )


# --- the scan card [0014.48] ---------------------------------------------------------------------


def test_the_scan_card_says_a_scan_reads_only_and_scan_now_is_the_primary_button(
    window_en: Window,
) -> None:
    # [0014.48]
    page = window_en.overview
    assert page.scan_card.property("role") == "card"
    assert page.scan_card.property("tone") == "surface"
    assert page.scan_title.text() == "Scan"
    assert page.scan_text.text() == "Read-only: a scan never changes anything on the disk."
    assert page.scan_button.text() == "Scan now"
    assert page.scan_button.property("role") == "primary"
    assert page.scan_button.parentWidget() is not None
    button_top = page.scan_button.mapTo(page.scan_card, page.scan_button.rect().topLeft())
    title_top = page.scan_title.mapTo(page.scan_card, page.scan_title.rect().topLeft())
    assert button_top.x() > title_top.x()
    assert button_top.y() == title_top.y()


@pytest.fixture
def window_en(qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path) -> Window:
    return make_window(qtbot, environment(tmp_path, zone, data_dir))


def test_the_last_scan_says_when_how_many_files_the_duplicate_groups_and_the_skips(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.48] With the default thresholds: 800 days unchanged is old.
    (zone / "link").symlink_to(tree["notes"])
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    before = time.time()
    scanned(qtbot, window)
    page = window.overview
    found = page.scanned
    assert found is not None
    assert before <= found.at <= time.time()
    assert page.last.text() == (
        f"Last scan {_moment(found.at)} · 8 files scanned · duplicates: 2 groups · skipped: 1 path"
    )
    assert page.last.property("role") == "caption"
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
    assert window.overview.levels[Level.SAFE].files.text().startswith("5 files: ")
    assert window.overview.levels[Level.SAFE].amount.text() == "36 B"


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


# --- a card per level [0014.48] ------------------------------------------------------------------


def test_after_a_scan_a_card_per_level_with_its_size_its_files_and_their_strongest_reasons(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.19] [0014.48]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    scanned(qtbot, window)
    page = window.overview
    assert not page.level_cards.isHidden()
    assert list(page.levels) == list(Level)
    shown = {
        level: (card.name.text(), card.amount.text(), card.files.text(), card.link.text())
        for level, card in page.levels.items()
    }
    assert shown == {
        Level.SAFE: ("Safe", "31 B", "4 files: cache", "Review findings →"),
        Level.LIKELY_SAFE: ("Likely safe", "10 B", "1 file: duplicate copy", "Review findings →"),
        Level.REVIEW: (
            "Review",
            "10 B",
            "1 file: not changed for a long time. Never proposed: you decide one by one.",
            "Look at them →",
        ),
    }
    for level, card in page.levels.items():
        assert card.property("role") == "card"
        assert card.dot.property("dot") == level.value
        assert card.amount.property("role") == "figure"
        assert card.link.property("role") == "link"


def test_a_level_without_files_says_so(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.48]
    write(zone / "proj" / "__pycache__" / "m.cpython-313.pyc", b"bytecode")
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    scanned(qtbot, window)
    cards = window.overview.levels
    assert cards[Level.LIKELY_SAFE].files.text() == "0 files"
    assert cards[Level.LIKELY_SAFE].amount.text() == "0 B"
    assert cards[Level.REVIEW].files.text() == ("0 files. Never proposed: you decide one by one.")


@pytest.mark.parametrize("level", list(Level))
def test_a_level_s_link_opens_findings_with_that_level_only(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path], level: Level
) -> None:
    # [0014.48]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    scanned(qtbot, window)
    findings = window.findings
    findings.search.setText("nothing matches this")
    window.overview.levels[level].link.click()
    assert window.pages.currentWidget() is findings
    assert {shown: box.isChecked() for shown, box in findings.filters.items()} == {
        shown: shown is level for shown in Level
    }
    assert findings.search.text() == ""
    shown = [
        finding.level
        for finding in findings.findings()
        if not findings.item(finding.entry.path).isHidden()
    ]
    assert shown
    assert shown == [finding.level for finding in findings.findings() if finding.level is level]


def test_the_cards_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.48]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), language="ru")
    page = window.overview
    assert page.last.text() == "Сканирования ещё не было."
    assert page.scan_button.text() == "Сканировать"
    assert page.add_button.text() == "Добавить папку"
    scanned(qtbot, window)
    found = page.scanned
    assert found is not None
    assert page.last.text() == (
        f"Последнее сканирование {_moment(found.at)} · просканировано: 8 файлов"
        " · дубликаты: 2 группы · пропущено: 0 путей"
    )
    shown = {level: (card.name.text(), card.files.text()) for level, card in page.levels.items()}
    assert shown == {
        Level.SAFE: ("Безопасно", "4 файла: кэш"),
        Level.LIKELY_SAFE: ("Скорее безопасно", "1 файл: копия дубликата"),
        Level.REVIEW: (
            "Проверить",
            "1 файл: давно не изменялся. Никогда не предлагается: решаете вы, по одному.",
        ),
    }
    assert page.levels[Level.REVIEW].link.text() == "Посмотреть их →"


# --- Quarantine, Organize and Autostart [0014.48] ------------------------------------------------


def _service(window: Window, name: str) -> tuple[str, str, str]:
    card = window.overview.services[name]
    return card.name.text(), card.main.text(), card.note.text()


def test_before_the_window_read_them_the_cards_say_what_the_pages_do(window_en: Window) -> None:
    # [0014.48]
    services = window_en.overview.services
    assert list(services) == ["quarantine", "organize", "autostart"]
    assert [card.icon.name for card in services.values()] == ["archive", "folder", "power"]
    assert _service(window_en, "quarantine") == (
        "Quarantine",
        "Moved files wait here",
        "Each can be put back where it was",
    )
    assert _service(window_en, "organize") == (
        "Organize",
        "Sort one folder by kind",
        "Nothing is renamed, overwritten or deleted",
    )
    assert _service(window_en, "autostart") == (
        "Autostart",
        "Programs that start at sign-in",
        "Turning one off can be undone",
    )


def test_the_cards_say_what_the_window_last_read(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    tree: dict[str, Path],
    home: Path,
) -> None:
    # [0014.48]
    folder = three_files(zone)
    entry = "[Desktop Entry]\nType=Application\nName={name}\nExec=/usr/bin/{name}\n"
    for name in ("one", "two"):
        write(
            tmp_path / "config" / "autostart" / f"{name}.desktop", entry.format(name=name).encode()
        )
    dialogs = FakeDialogs(folders=[folder])
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), dialogs=dialogs)
    scanned(qtbot, window)
    window.findings.move_button.click()  # n, m and copy: 8 + 15 + 4 bytes
    wait_idle(qtbot, window)
    window.show_page("quarantine")
    wait_idle(qtbot, window)
    assert _service(window, "quarantine") == (
        "Quarantine",
        "3 files · 27 B",
        "Each can be put back where it was",
    )
    window.show_page("organize")
    wait_idle(qtbot, window)
    window.organize.choose_button.click()
    wait_idle(qtbot, window)
    assert _service(window, "organize") == (
        "Organize",
        f"3 files in {Path('~') / 'zone' / 'Downloads'}",
        "Can be sorted into 3 folders",
    )
    window.organize.move_button.click()  # once sorted, the plan is no longer what is there
    wait_idle(qtbot, window)
    assert _service(window, "organize")[1] == "Sort one folder by kind"
    window.show_page("autostart")
    wait_idle(qtbot, window)
    assert _service(window, "autostart")[1:] == ("2 entries", "0 turned off")


def test_a_click_on_a_card_opens_its_page(window_en: Window) -> None:
    # [0014.48]
    for name, card in window_en.overview.services.items():
        window_en.show_page("overview")
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=card.rect().center())
        assert window_en.pages.currentWidget() is window_en.page(name)


def test_a_card_opens_its_page_from_the_keyboard_too(qtbot: QtBot, window_en: Window) -> None:
    # [0014.48] [0014.18]
    card = window_en.overview.services["autostart"]
    assert card.focusPolicy() & Qt.FocusPolicy.TabFocus
    assert card.accessibleName() == "Autostart"
    QTest.keyClick(card, Qt.Key.Key_A)
    assert window_en.pages.currentWidget() is window_en.page("overview")
    QTest.keyClick(card, Qt.Key.Key_Return)
    assert window_en.pages.currentWidget() is window_en.page("autostart")
    window_en.show_page("overview")
    QTest.keyClick(window_en.overview.services["quarantine"], Qt.Key.Key_Space)
    assert window_en.pages.currentWidget() is window_en.page("quarantine")


def test_a_click_that_ends_outside_a_card_opens_nothing(window_en: Window) -> None:
    # [0014.48]
    card = window_en.overview.services["organize"]
    QTest.mouseClick(card, Qt.MouseButton.RightButton, pos=card.rect().center())
    assert window_en.pages.currentWidget() is window_en.page("overview")
    QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=card.rect().center())
    QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=card.rect().bottomRight() * 2)
    assert window_en.pages.currentWidget() is window_en.page("overview")


def test_the_cards_of_a_row_are_as_wide_as_each_other_and_their_words_start_at_the_top(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0014.48] Even when a card has a long folder to say.
    folder = three_files(zone)
    dialogs = FakeDialogs(folders=[folder])
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), dialogs=dialogs)
    window.resize(1200, 780)
    scanned(qtbot, window)
    window.show_page("organize")
    wait_idle(qtbot, window)
    window.organize.choose_button.click()
    wait_idle(qtbot, window)
    window.show_page("overview")
    page = window.overview
    qtbot.waitUntil(lambda: page.level_cards.isVisible())
    for row in (list(page.levels.values()), list(page.services.values())):
        widths = [shown.width() for shown in row]
        assert max(widths) - min(widths) <= 1  # what the row cannot share out evenly
    for service in page.services.values():
        assert service.name.geometry().top() == service.icon.geometry().top()
        assert service.main.geometry().top() < service.note.geometry().top()
        assert service.note.geometry().top() - service.main.geometry().bottom() <= 8
