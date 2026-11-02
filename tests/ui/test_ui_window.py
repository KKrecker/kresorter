"""The window: the sidebar and its pages, one task at a time, closing (decision 0014, items
16-18)."""

import threading
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QWidget
from pytestqt.qtbot import QtBot

from safeclean.ui.i18n import Language, Translator
from safeclean.ui.sidebar import NAV_ROW
from safeclean.ui.tasks import Task
from safeclean.ui.window import PAGES, Window
from support.window import environment, unnamed, wait_idle


def _make(qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, language: Language) -> Window:
    window = Window(environment(tmp_path, zone, data_dir), Translator(language))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    wait_idle(qtbot, window)
    return window


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path) -> Window:
    return _make(qtbot, tmp_path, zone, data_dir, "en")


def _nothing(result: object) -> None:
    return None


def _shown(window: Window) -> list[str]:
    return [window.sidebar.text(row) for row in range(window.sidebar.count())]


# --- navigation [0014.18] ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "names"),
    [
        ("en", ["Overview", "Findings", "Organize", "Autostart", "Quarantine", "Settings"]),
        ("ru", ["Обзор", "Находки", "Сортировка", "Автозагрузка", "Карантин", "Настройки"]),
    ],
)
def test_the_sidebar_opens_the_six_pages_in_order_and_settings_apart(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, language: Language, names: list[str]
) -> None:
    # [0014.18]
    window = _make(qtbot, tmp_path, zone, data_dir, language)
    assert PAGES == ("overview", "findings", "organize", "autostart", "quarantine", "settings")
    assert window.sidebar.objectName() == "sidebar"
    assert _shown(window) == names
    top, bottom = window.sidebar.lists
    assert [top.item(row).text() for row in range(top.count())] == names[:-1]
    assert [bottom.item(row).text() for row in range(bottom.count())] == names[-1:]
    assert bottom.geometry().top() > top.geometry().bottom() + 2 * NAV_ROW  # at the bottom
    assert window.pages.count() == len(PAGES)
    assert [window.page(name) for name in PAGES] == [
        window.pages.widget(index) for index in range(len(PAGES))
    ]


def test_the_current_page_is_marked(window: Window) -> None:
    # [0014.18]
    assert window.pages.currentIndex() == 0
    assert window.sidebar.marked() == [0]
    window.show_page("quarantine")
    assert window.pages.currentWidget() is window.page("quarantine")
    assert window.sidebar.currentRow() == 4
    assert window.sidebar.marked() == [4]
    window.sidebar.setCurrentRow(3)
    assert window.pages.currentWidget() is window.page("autostart")
    assert window.sidebar.marked() == [3]
    window.show_page("settings")
    assert window.pages.currentWidget() is window.page("settings")
    assert window.sidebar.marked() == [5]


def test_every_page_is_reachable_with_the_keyboard(window: Window) -> None:
    # [0014.18]
    sidebar = window.sidebar
    assert all(listed.focusPolicy() & Qt.FocusPolicy.TabFocus for listed in sidebar.lists)
    reached = [window.pages.currentIndex()]
    for _ in PAGES[1:]:
        QTest.keyClick(sidebar.current_list(), Qt.Key.Key_Down)
        reached.append(window.pages.currentIndex())
    assert reached == list(range(len(PAGES)))
    QTest.keyClick(sidebar.current_list(), Qt.Key.Key_Home)
    assert window.pages.currentIndex() == 0
    assert sidebar.marked() == [0]


def test_buttons_without_a_text_or_an_accessible_name_are_found(qtbot: QtBot) -> None:
    # [0014.18]
    holder = QWidget()
    qtbot.addWidget(holder)
    named, labelled, bare = QPushButton("Scan", holder), QPushButton(holder), QPushButton(holder)
    labelled.setAccessibleName("Remove the folder")
    bare.setText("  ")
    assert unnamed(holder) == [bare]
    assert named.text() == "Scan"


def test_every_button_has_a_text_or_an_accessible_name(window: Window) -> None:
    # [0014.18]
    assert unnamed(window) == []


# --- one task at a time [0014.16] ----------------------------------------------------------------


def test_while_a_task_runs_what_starts_a_task_is_disabled_and_the_window_says_what_runs(
    qtbot: QtBot, window: Window
) -> None:
    # [0014.16]
    scan = QPushButton("Scan", window)
    move = QPushButton("Move", window)
    selected: list[bool] = [False]
    window.add_starter(scan)
    window.add_starter(move, when=lambda: selected[0])
    assert (scan.isEnabled(), move.isEnabled()) == (True, False)
    selected[0] = True
    window.update_starters()
    assert (scan.isEnabled(), move.isEnabled()) == (True, True)
    assert window.status.text() == ""

    release = threading.Event()
    assert window.run(Task("Scanning", lambda: release.wait(timeout=10), _nothing))
    assert (scan.isEnabled(), move.isEnabled()) == (False, False)
    assert window.status.text() == "Running: Scanning"
    window.update_starters()  # a page's own condition never enables them while a task runs
    assert (scan.isEnabled(), move.isEnabled()) == (False, False)
    assert not window.run(Task("Second", lambda: None, _nothing))

    release.set()
    qtbot.waitUntil(lambda: scan.isEnabled())
    assert move.isEnabled()
    assert window.status.text() == ""


def _raise(error: Exception) -> None:
    raise error


def test_an_error_is_shown_with_its_message_and_the_window_stays_usable(
    qtbot: QtBot, window: Window
) -> None:
    # [0014.16]
    scan = QPushButton("Scan", window)
    window.add_starter(scan)
    assert window.run(Task("Scanning", lambda: _raise(OSError("disk on fire")), _nothing))
    qtbot.waitUntil(lambda: window.message.text() != "")
    assert window.message.text() == "Scanning failed: disk on fire"
    assert scan.isEnabled()
    assert window.status.text() == ""
    results: list[str] = []
    assert window.run(Task("Again", lambda: "again", results.append))
    assert window.message.text() == ""  # a new task clears the last message
    qtbot.waitUntil(lambda: results == ["again"])


def test_the_window_says_what_runs_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.16]
    window = _make(qtbot, tmp_path, zone, data_dir, "ru")
    release = threading.Event()
    assert window.run(Task("Сканирование", lambda: release.wait(timeout=10), _nothing))
    assert window.status.text() == "Выполняется: Сканирование"
    release.set()
    qtbot.waitUntil(lambda: window.status.text() == "")
    assert window.run(Task("Сканирование", lambda: _raise(OSError("нет места")), _nothing))
    qtbot.waitUntil(lambda: window.message.text() != "")
    assert window.message.text() == "Ошибка (Сканирование): нет места"


# --- closing waits for what acts [0014.17] -------------------------------------------------------


def test_without_a_task_the_window_closes(window: Window) -> None:
    # [0014.17]
    assert window.close()
    assert not window.isVisible()


def test_closing_while_a_task_that_acts_runs_is_refused_then_it_closes_after_it(
    qtbot: QtBot, window: Window
) -> None:
    # [0014.17]
    release = threading.Event()
    results: list[bool] = []
    moving = Task("Moving to quarantine", lambda: release.wait(timeout=10), results.append, True)
    assert window.run(moving)
    assert not window.close()
    assert window.isVisible()
    assert window.message.text() == (
        "Moving to quarantine is still running; the window closes when it ends."
    )
    release.set()
    qtbot.waitUntil(lambda: not window.isVisible())
    assert results == [True]  # its result is applied first


def test_a_task_that_only_reads_is_left_behind_when_the_window_closes(
    qtbot: QtBot, window: Window
) -> None:
    # [0014.17]
    release = threading.Event()
    ended = threading.Event()
    results: list[bool] = []

    def work() -> bool:
        try:
            return release.wait(timeout=10)
        finally:
            ended.set()

    assert window.run(Task("Scanning", work, results.append))
    assert window.close()
    assert not window.isVisible()
    release.set()
    assert ended.wait(timeout=10)
    qtbot.wait(100)
    assert results == []
