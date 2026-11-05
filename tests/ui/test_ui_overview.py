"""The Overview page: the scan card with the folders as chips, what the last scan found a card
per level, and a card each for Quarantine, Organize and Autostart (decision 0014, items 19
and 48)."""

import dataclasses
import json
import threading
import time
from collections.abc import Sequence
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from fakes import UnreliableOpenFiles, make_policy
from kresorter.analysis.report import AnalysisReport
from kresorter.analysis.run import analyze_paths
from kresorter.analysis.score import Level
from kresorter.analysis.size_age import Thresholds
from kresorter.core.open_files.windows import ShareModeChecker
from kresorter.core.scanner import Progress, ScanContext, ScanReport
from kresorter.environment import Environment
from kresorter.storage.session import SessionFailed, SessionFailure
from kresorter.ui import overview, settings_page
from kresorter.ui.overview import FolderChip
from kresorter.ui.shown import shown_path
from kresorter.ui.tasks import Task
from kresorter.ui.window import Window
from support.files import write
from support.kernel import FakeKernel
from support.moves import three_files
from support.window import (
    FakeDialogs,
    environment,
    junk_tree,
    make_window,
    scanned,
    settled,
    wait_idle,
)


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
    # [0014.19] [0014.48] A chip each: the folder icon and the path; a safe zone's with a
    # remove button too, that leaves it out [0018.17].
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    page = window.overview
    assert _folders(window) == [zone]
    assert page.roots() == [zone]
    [chip] = _chips(window)
    assert chip.icon.name == "folder"
    assert chip.label.text() == str(Path("~") / "zone")
    assert chip.toolTip() == str(zone)
    assert chip.remove.accessibleName() == f"Leave {Path('~') / 'zone'} out of the scan"
    assert chip.property("role") == "chip"
    assert page.add_button.text() == "Add folder"
    assert page.add_button.property("role") == "plain"
    assert page.level_cards.isHidden()
    assert page.last.text() == "Not scanned yet."


def test_folders_the_user_adds_can_be_removed_again(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, home: Path
) -> None:
    # [0014.19] [0014.48] A folder added twice is listed once; a dialog closed adds none; an
    # added folder's chip has a remove button.
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

    _, extra_chip, _ = _chips(window)
    assert extra_chip.remove.accessibleName() == f"Remove folder {Path('~') / 'extra'}"
    assert extra_chip.remove.toolTip() == extra_chip.remove.accessibleName()
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
    write(extra / "Thumbs.db", b"extra")
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


def test_with_the_windows_check_the_page_says_nothing_of_it(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, tree: dict[str, Path]
) -> None:
    # [0016.5] the note about an unreliable check is not shown on Windows
    checked = ShareModeChecker(FakeKernel())
    window = make_window(
        qtbot, environment(tmp_path, zone, data_dir, platform="windows", open_files=checked)
    )
    scanned(qtbot, window)
    assert window.overview.unreliable.isHidden()


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
        Level.SAFE: ("Safe", "31 B", "4 files: thumbnails", "Review findings →"),
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
    write(zone / "proj" / "Thumbs.db", b"bytecode")
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
        Level.SAFE: ("Безопасно", "4 файла: миниатюры"),
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


OPENS = {"quarantine": "quarantine", "organize": "organize", "autostart": "autostart"}


def test_before_the_window_read_them_the_cards_say_what_the_pages_do(window_en: Window) -> None:
    # [0014.48] The local AI's card the fourth [0018.35].
    services = window_en.overview.services
    assert list(services) == ["quarantine", "organize", "autostart", "ai"]
    icons = [card.icon.name for card in services.values()]
    assert icons == ["archive", "folder", "power", "sparkles"]
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
    # [0014.48] The local AI's opens Settings [0018.35].
    for name, card in window_en.overview.services.items():
        window_en.show_page("overview")
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=card.rect().center())
        opened = OPENS.get(name, "settings")
        assert window_en.pages.currentWidget() is window_en.page(opened)


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


# --- the scan's progress [0018.16] ---------------------------------------------------------------


def test_while_a_scan_runs_the_status_line_counts_the_files_read_at_most_ten_times_a_second(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    tree: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0018.16] The window's scan uses the scan's progress; the line is redrawn at most every
    # tenth of a second, and says only what runs once the scan ends.
    released = threading.Event()

    def slow(
        paths: list[str],
        context: ScanContext,
        thresholds: Thresholds,
        *,
        junk_only: Sequence[Path],
        progress: Progress,
    ) -> tuple[ScanReport, AnalysisReport]:
        progress(1500)
        released.wait(10)
        return analyze_paths(paths, context, thresholds, junk_only=junk_only, progress=progress)

    monkeypatch.setattr(overview, "analyze_paths", slow)
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), language="ru")
    window.overview.scan_button.click()
    qtbot.waitUntil(
        lambda: window.status.text() == "Выполняется: Сканирование, прочитано 1500 файлов"
    )
    assert window.progress_timer.isActive()
    assert window.progress_timer.interval() >= 100
    released.set()
    wait_idle(qtbot, window)
    assert window.status.text() == ""
    assert not window.progress_timer.isActive()
    assert window.overview.scanned is not None


def test_a_task_without_progress_says_only_what_runs(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.16]
    released = threading.Event()
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    window.run(Task("Waiting", lambda: released.wait(10), lambda _: None))
    assert window.status.text() == "Running: Waiting"
    assert not window.progress_timer.isActive()
    released.set()
    wait_idle(qtbot, window)


# --- the zones left out and put back [0018.17] [0018.18] ------------------------------------------


def _zones(tmp_path: Path, data_dir: Path) -> tuple[Environment, list[Path]]:
    """Two safe zones, as a system has them: ``~/.cache`` and ``~/Downloads``."""
    zones = [tmp_path / ".cache", tmp_path / "Downloads"]
    for zone in zones:
        zone.mkdir()
    base = environment(tmp_path, zones[0], data_dir)

    def context() -> ScanContext:
        system = tmp_path / "system"
        policy = make_policy(tmp_path, system, default_roots=zones, app_data_dir=data_dir)
        return dataclasses.replace(base.scan_context(), policy=policy)

    return dataclasses.replace(base, scan_context=context), zones


def _links(window: Window) -> list[str]:
    return [link.text() for link in window.overview.zone_links()]


def _skipped(data_dir: Path) -> object:
    return json.loads((data_dir / "settings.json").read_text(encoding="utf-8"))["skipped_zones"]


def _shown(name: str) -> str:
    return str(Path("~") / name)


def test_a_safe_zone_s_chip_has_a_remove_button_and_a_zone_left_out_is_not_scanned(
    qtbot: QtBot, tmp_path: Path, data_dir: Path, home: Path
) -> None:
    # [0018.17] As an added folder's chip; the window remembers the zone's name.
    env, zones = _zones(tmp_path, data_dir)
    write(zones[0] / "a.bin", b"a")
    write(zones[1] / "b.bin", b"b")
    window = make_window(qtbot, env)
    first, _ = _chips(window)
    assert first.remove.accessibleName() == f"Leave {_shown('.cache')} out of the scan"
    assert first.remove.toolTip() == first.remove.accessibleName()
    first.remove.click()
    assert _folders(window) == [zones[1]]
    assert _links(window) == [f"+ {_shown('.cache')}"]
    assert _skipped(data_dir) == [".cache"]
    scanned(qtbot, window)
    assert window.overview.scanned is not None
    assert [e.path for e in window.overview.scanned.report.entries] == [zones[1] / "b.bin"]


def test_a_zone_left_out_stays_out_when_the_window_opens_again(
    qtbot: QtBot, tmp_path: Path, data_dir: Path, home: Path
) -> None:
    # [0018.17]
    env, zones = _zones(tmp_path, data_dir)
    settled(data_dir, skipped_zones=["Downloads"])
    window = make_window(qtbot, env)
    assert _folders(window) == [zones[0]]
    assert window.overview.roots() == [zones[0]]
    assert _links(window) == [f"+ {_shown('Downloads')}"]


def test_the_link_puts_the_zone_back_where_it_was_and_saves(
    qtbot: QtBot, tmp_path: Path, data_dir: Path, home: Path
) -> None:
    # [0018.18] A link each, at the end of the folders.
    env, zones = _zones(tmp_path, data_dir)
    extra = tmp_path / "extra"
    extra.mkdir()
    settled(data_dir, skipped_zones=[".cache", "Downloads"])
    window = make_window(qtbot, env, dialogs=FakeDialogs(folders=[extra]))
    page = window.overview
    page.add_button.click()
    assert _folders(window) == [extra]
    assert _links(window) == [f"+ {_shown('.cache')}", f"+ {_shown('Downloads')}"]
    cache, downloads = page.zone_links()
    assert cache.property("role") == "link"
    assert cache.toolTip() == f"Scan {_shown('.cache')} again"
    last = _chips(window)[-1]

    def after_the_folders() -> bool:
        right = last.mapTo(page, last.rect().topRight()).x()
        return cache.mapTo(page, cache.rect().topLeft()).x() > right

    qtbot.waitUntil(lambda: cache.isVisible() and last.isVisible())
    qtbot.waitUntil(after_the_folders)
    downloads.click()
    assert _folders(window) == [zones[1], extra]
    assert _links(window) == [f"+ {_shown('.cache')}"]
    assert _skipped(data_dir) == [".cache"]
    cache.click()
    assert _folders(window) == [*zones, extra]
    assert _links(window) == []
    assert _skipped(data_dir) == []


def test_with_no_folder_at_all_scan_now_is_disabled(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.18]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    page = window.overview
    assert page.scan_button.isEnabled()
    [chip] = _chips(window)
    chip.remove.click()
    assert page.roots() == []
    assert not page.scan_button.isEnabled()
    [link] = page.zone_links()
    link.click()
    assert page.roots() == [zone]
    assert page.scan_button.isEnabled()


def test_a_zone_that_cannot_be_remembered_stays_and_the_window_says_why(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.17] As a setting that cannot be saved: nothing changes.
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    data_dir.write_bytes(b"not a directory")
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    [chip] = _chips(window)
    chip.remove.click()
    assert _folders(window) == [zone]
    assert window.overview.zone_links() == []
    assert window.message.text().startswith("Not saved: The data folder cannot be used: ")
    assert window.settings.current.skipped_zones == ()


def test_a_zone_that_cannot_be_put_back_stays_out_and_the_window_says_why(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0018.18] As a setting that cannot be saved: nothing changes.
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    [chip] = _chips(window)
    chip.remove.click()
    failed = SessionFailed(SessionFailure.DATA_DIR_OS, "No space left on device")
    monkeypatch.setattr(settings_page, "save", lambda context, settings: failed)
    [link] = window.overview.zone_links()
    link.click()
    assert window.overview.roots() == []
    assert window.overview.zone_links() == [link]
    assert window.message.text().startswith("Not saved: ")
    assert "No space left on device" in window.message.text()
    assert window.settings.current.skipped_zones == ("zone",)


def test_a_scan_asked_for_while_a_task_runs_does_not_start(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.9] As Scan again on Findings would while the window works: no bar either.
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    released = threading.Event()
    assert window.run(Task("Waiting", lambda: released.wait(10), lambda _: None))
    window.overview.start_scan()
    assert window.status.text() == "Running: Waiting"
    assert window.overview.scan_bar.isHidden()
    released.set()
    wait_idle(qtbot, window)
    assert window.overview.scanned is None


def test_the_zones_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, home: Path
) -> None:
    # [0018.17] [0018.18]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), language="ru")
    [chip] = _chips(window)
    assert chip.remove.accessibleName() == f"Убрать {_shown('zone')} из сканирования"
    chip.remove.click()
    [link] = window.overview.zone_links()
    assert link.text() == f"+ {_shown('zone')}"
    assert link.toolTip() == f"Снова сканировать {_shown('zone')}"


def test_a_zone_left_out_that_is_added_as_a_folder_is_put_back(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.18] Where it was, as its link does: never twice.
    window = make_window(
        qtbot, environment(tmp_path, zone, data_dir), dialogs=FakeDialogs(folders=[zone])
    )
    _chips(window)[0].remove.click()
    window.overview.add_button.click()
    assert window.overview.roots() == [zone]
    assert window.overview.zone_links() == []
    assert window.settings.current.skipped_zones == ()


# --- the programs' caches [0020.15] ---------------------------------------------------------------


def _caches(tmp_path: Path, zone: Path, data_dir: Path) -> tuple[Environment, list[Path]]:
    """A system with a zone of programs' caches, as Windows has: one folder made, one not."""
    caches = [tmp_path / "Local" / "Chrome", tmp_path / "Local" / "NVIDIA"]
    caches[0].mkdir(parents=True)
    base = environment(tmp_path, zone, data_dir)

    def context() -> ScanContext:
        policy = make_policy(
            tmp_path,
            tmp_path / "system",
            default_roots=[zone],
            app_data_dir=data_dir,
            cache_zone=caches,
        )
        return dataclasses.replace(base.scan_context(), policy=policy)

    return dataclasses.replace(base, scan_context=context), caches


def test_the_programs_caches_are_a_chip_after_the_safe_zones(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, home: Path
) -> None:
    # [0020.15] by its name; its folders in its tooltip
    env, caches = _caches(tmp_path, zone, data_dir)
    window = make_window(qtbot, env)
    first, chip = _chips(window)
    assert first.path == zone
    assert chip.label.text() == "Programs' caches"
    assert chip.toolTip() == "\n".join(["Read for junk only:", *(str(c) for c in caches)])
    assert chip.remove.accessibleName() == "Leave Programs' caches out of the scan"
    assert window.overview.roots() == [zone]
    assert window.overview.junk_only() == caches


def test_the_programs_caches_are_read_for_junk_only(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, home: Path
) -> None:
    # [0020.15] where its folders are; the Findings page says it read them
    env, caches = _caches(tmp_path, zone, data_dir)
    junk = write(caches[0] / "__pycache__" / "m.cpython-313.pyc", b"bytecode")
    write(caches[0] / "photo.jpg", b"same")
    write(zone / "photo.jpg", b"same")
    window = make_window(qtbot, env)
    scanned(qtbot, window)
    found = window.overview.scanned
    assert found is not None
    assert found.report.junk_only_roots == (caches[0],)
    assert [finding.entry.path for finding in found.analysis.findings] == [junk]
    subtitle = window.findings.head.subtitle.text()
    assert subtitle == f"Scan of {_shown('zone')} and programs' caches, {_moment(found.at)}"


def test_the_programs_caches_left_out_are_remembered_and_put_back(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, home: Path
) -> None:
    # [0020.15] like any zone, by the name caches
    env, caches = _caches(tmp_path, zone, data_dir)
    write(caches[0] / "__pycache__" / "m.cpython-313.pyc", b"bytecode")
    window = make_window(qtbot, env)
    _, chip = _chips(window)
    chip.remove.click()
    assert _links(window) == ["+ Programs' caches"]
    assert _skipped(data_dir) == ["caches"]
    assert window.overview.junk_only() == []
    scanned(qtbot, window)
    found = window.overview.scanned
    assert found is not None
    assert (found.report.junk_only_roots, found.analysis.findings) == ((), ())
    subtitle = window.findings.head.subtitle.text()
    assert subtitle == f"Scan of {_shown('zone')}, {_moment(found.at)}"
    [link] = window.overview.zone_links()
    assert link.toolTip() == "Scan Programs' caches again"
    link.click()
    assert [c.label.text() for c in _chips(window)] == [_shown("zone"), "Programs' caches"]
    assert _skipped(data_dir) == []


def test_the_programs_caches_alone_are_scanned_and_said_so_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, home: Path
) -> None:
    # [0020.15]
    env, caches = _caches(tmp_path, zone, data_dir)
    settled(data_dir, skipped_zones=["zone"])
    window = make_window(qtbot, env, language="ru")
    [chip] = _chips(window)
    assert chip.label.text() == "Кеши программ"
    assert chip.toolTip() == "\n".join(["Только поиск мусора:", *(str(c) for c in caches)])
    assert chip.remove.accessibleName() == "Убрать Кеши программ из сканирования"
    assert window.overview.roots() == []
    assert window.overview.scan_button.isEnabled()
    scanned(qtbot, window)
    found = window.overview.scanned
    assert found is not None
    subtitle = window.findings.head.subtitle.text()
    assert subtitle == f"Сканирование кешей программ, {_moment(found.at)}"
