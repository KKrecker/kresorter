"""The sidebar: the mark, the pages with their icons and numbers, Settings apart, the status
lines of the open-file check and the local AI (decision 0014, items 18 and 45)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QListWidget
from pytestqt.qtbot import QtBot

from fakes import UnreliableOpenFiles
from kresorter.analysis.score import Level
from kresorter.llm.settings import MODEL_VARIABLE, URL_VARIABLE
from kresorter.ui import icons
from kresorter.ui.sidebar import ICONS, NAV_ROW, WIDTH, nav_style
from kresorter.ui.theme import DARK, LIGHT, Palette
from kresorter.ui.window import PAGES, Window
from support.drawn import drawn_in
from support.ollama import TAGS, VERSION, ScriptedOllama, as_json
from support.window import environment, junk_tree, make_window, scanned, wait_idle

FINDINGS, QUARANTINE = PAGES.index("findings"), PAGES.index("quarantine")


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path) -> Window:
    return make_window(qtbot, environment(tmp_path, zone, data_dir))


@pytest.fixture
def dark(qapp: QApplication) -> Iterator[None]:
    """The system's scheme turns dark, once the window is open (offscreen reports none)."""
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    yield
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)


def _palette(window: Window) -> Palette:
    return window.look.palette


def _colour(image: QImage, x: int, y: int) -> str:
    return image.pixelColor(x, y).name().upper()


def _row(window: Window, row: int) -> tuple[QListWidget, QRect]:
    """The list a page is in, and its row's rectangle there."""
    sidebar = window.sidebar
    top = sidebar.lists[0].count()
    listed = sidebar.lists[0] if row < top else sidebar.lists[1]
    item = sidebar.item(row)
    return listed, listed.visualItemRect(item)


def _drawn(window: Window, row: int, left: int, right: int) -> QImage:
    """What a page's row draws between ``left`` and ``right`` (from its left)."""
    listed, rect = _row(window, row)
    image = listed.viewport().grab().toImage()
    return image.copy(QRect(rect.left() + left, rect.top() + 4, right - left, rect.height() - 8))


def _count_drawn(window: Window, row: int) -> bool:
    _, rect = _row(window, row)
    palette = _palette(window)
    ground = palette.surface2 if row == window.sidebar.currentRow() else palette.surface
    number = _drawn(window, row, rect.width() - 40, rect.width() - 4)
    return drawn_in(number, palette.secondary, ground, within=12)


# --- the sidebar and the mark --------------------------------------------------------------------


def test_the_sidebar_is_232_px_wide_on_surface_with_a_border_at_its_right(
    window: Window,
) -> None:
    # [0014.45]
    sidebar = window.sidebar
    assert WIDTH == 232
    assert sidebar.width() == WIDTH
    assert sidebar.minimumWidth() == sidebar.maximumWidth() == WIDTH
    shown = sidebar.grab().toImage()
    palette = _palette(window)
    assert _colour(shown, WIDTH - 1, 4) == palette.border
    assert _colour(shown, WIDTH - 2, 4) == palette.surface
    assert _colour(shown, 1, shown.height() // 2) == palette.surface


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_mark_is_the_shield_on_the_accent_and_beside_it_kresorter(
    request: pytest.FixtureRequest, window: Window, scheme: str
) -> None:
    # [0014.45]
    if scheme == "dark":
        request.getfixturevalue("dark")
    palette = DARK if scheme == "dark" else LIGHT
    assert _palette(window) is palette
    mark = window.sidebar.mark
    assert mark.name == "shield-check"
    assert mark.colours() == (palette.primary_text, palette.accent)
    assert (mark.width(), mark.height()) == (28, 28)
    shown = mark.grab().toImage()
    assert _colour(shown, 14, 2) == palette.accent
    assert _colour(shown, 0, 0) != palette.accent  # the tile's corners are round
    assert drawn_in(shown, palette.primary_text, palette.accent)
    brand = window.sidebar.findChild(QLabel, "brand")
    assert brand is not None
    assert brand.text() == "Kresorter"


# --- the pages -----------------------------------------------------------------------------------


def test_every_page_has_its_lucide_icon() -> None:
    # [0014.45]
    assert set(ICONS) == set(PAGES)
    assert set(ICONS.values()) <= set(icons.NAMES)
    assert len(set(ICONS.values())) == len(PAGES)


def test_the_current_page_is_on_surface_2_in_semibold_the_others_secondary_icons() -> None:
    # [0014.45]
    for palette in (LIGHT, DARK):
        assert nav_style(palette, current=True) == (
            palette.surface2,
            palette.text,
            QFont.Weight.DemiBold,
        )
        assert nav_style(palette, current=False) == (None, palette.secondary, QFont.Weight.Normal)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_current_page_is_drawn_on_surface_2_and_the_others_on_surface(
    request: pytest.FixtureRequest, window: Window, scheme: str
) -> None:
    # [0014.45]
    if scheme == "dark":
        request.getfixturevalue("dark")
    palette = _palette(window)
    window.show_page("organize")
    current = PAGES.index("organize")
    for row in range(len(PAGES)):
        listed, rect = _row(window, row)
        assert rect.height() == NAV_ROW
        assert rect.width() == listed.viewport().width()
        image = listed.viewport().grab().toImage()
        middle = rect.center().y()
        ground = palette.surface2 if row == current else palette.surface
        assert _colour(image, rect.left() + 4, middle) == ground
        assert _colour(image, rect.left(), rect.top()) == palette.surface  # a radius of 8
        icon = _drawn(window, row, 8, 30)
        colour = palette.text if row == current else palette.secondary
        assert drawn_in(icon, colour, ground)
        assert drawn_in(_drawn(window, row, 40, 80), palette.text, ground)


def test_the_current_page_has_no_focus_rectangle(qtbot: QtBot, window: Window) -> None:
    # [0014.45]
    with qtbot.waitActive(window):
        window.activateWindow()
    listed = window.sidebar.lists[0]
    listed.setFocus()
    qtbot.waitUntil(listed.hasFocus)
    focused = listed.grab().toImage()
    window.overview.scan_button.setFocus()
    qtbot.waitUntil(lambda: not listed.hasFocus())
    assert listed.grab().toImage() == focused


def test_findings_and_quarantine_have_no_number_before_the_window_read_them(
    window: Window,
) -> None:
    # [0014.45]
    assert window.sidebar.count_of("findings") is None
    assert window.sidebar.count_of("quarantine") is None
    assert not _count_drawn(window, FINDINGS)
    assert not _count_drawn(window, QUARANTINE)


def test_findings_shows_the_number_of_findings_and_quarantine_of_its_files(
    qtbot: QtBot, window: Window, zone: Path
) -> None:
    # [0014.45]
    junk_tree(zone)
    scanned(qtbot, window)
    assert window.sidebar.count_of("findings") == 6
    assert _count_drawn(window, FINDINGS)
    assert window.sidebar.count_of("quarantine") is None
    window.show_page("quarantine")
    wait_idle(qtbot, window)
    assert window.sidebar.count_of("quarantine") == 0
    window.show_page("findings")
    window.findings.move_button.click()  # n, m and copy, selected at first
    wait_idle(qtbot, window)
    assert window.sidebar.count_of("findings") == 3
    assert window.sidebar.count_of("quarantine") == 0  # until the page reads it again
    window.show_page("quarantine")
    wait_idle(qtbot, window)
    assert window.sidebar.count_of("quarantine") == 3
    assert _count_drawn(window, QUARANTINE)


# --- the keyboard --------------------------------------------------------------------------------


def test_the_arrow_keys_cross_from_the_pages_to_settings_and_back(window: Window) -> None:
    # [0014.18] [0014.45]
    sidebar = window.sidebar
    reached = [sidebar.currentRow()]
    for _ in PAGES[1:]:
        QTest.keyClick(sidebar.current_list(), Qt.Key.Key_Down)
        reached.append(sidebar.currentRow())
    assert reached == list(range(len(PAGES)))
    assert sidebar.current_list() is sidebar.lists[1]
    QTest.keyClick(sidebar.current_list(), Qt.Key.Key_Down)  # Settings is the last
    assert sidebar.currentRow() == len(PAGES) - 1
    QTest.keyClick(sidebar.current_list(), Qt.Key.Key_Up)
    assert sidebar.currentRow() == len(PAGES) - 2
    assert sidebar.current_list() is sidebar.lists[0]
    assert sidebar.marked() == [len(PAGES) - 2]
    QTest.keyClick(sidebar.current_list(), Qt.Key.Key_Up)
    assert sidebar.currentRow() == len(PAGES) - 3


def test_home_and_end_go_to_the_first_page_and_to_settings(window: Window) -> None:
    # [0014.18] [0014.45]
    sidebar = window.sidebar
    QTest.keyClick(sidebar.current_list(), Qt.Key.Key_End)
    assert sidebar.currentRow() == len(PAGES) - 1
    assert window.pages.currentWidget() is window.page("settings")
    assert sidebar.marked() == [len(PAGES) - 1]
    QTest.keyClick(sidebar.current_list(), Qt.Key.Key_End)
    assert sidebar.currentRow() == len(PAGES) - 1
    QTest.keyClick(sidebar.current_list(), Qt.Key.Key_Home)
    assert sidebar.currentRow() == 0
    assert sidebar.marked() == [0]
    QTest.keyClick(sidebar.current_list(), Qt.Key.Key_Home)
    assert sidebar.currentRow() == 0


def test_the_focus_follows_the_current_page_from_one_list_to_the_other(
    qtbot: QtBot, window: Window
) -> None:
    # [0014.18]
    sidebar = window.sidebar
    with qtbot.waitActive(window):
        window.activateWindow()
    sidebar.lists[0].setFocus()
    qtbot.waitUntil(sidebar.lists[0].hasFocus)
    QTest.keyClick(sidebar.lists[0], Qt.Key.Key_End)
    qtbot.waitUntil(sidebar.lists[1].hasFocus)
    QTest.keyClick(sidebar.lists[1], Qt.Key.Key_Up)
    qtbot.waitUntil(sidebar.lists[0].hasFocus)
    assert sidebar.marked() == [len(PAGES) - 2]


def test_a_click_on_settings_unmarks_the_page_marked_before(window: Window) -> None:
    # [0014.18]
    sidebar = window.sidebar
    window.show_page("autostart")
    settings = sidebar.lists[1]
    rect = settings.visualItemRect(sidebar.item(len(PAGES) - 1))
    QTest.mouseClick(settings.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert sidebar.marked() == [len(PAGES) - 1]
    assert window.pages.currentWidget() is window.page("settings")
    assert sidebar.lists[0].currentRow() == -1


# --- the status lines ----------------------------------------------------------------------------


def _dot_colour(window: Window, which: str) -> str:
    shown = getattr(window.sidebar, f"{which}_dot").grab().toImage()
    return _colour(shown, shown.width() // 2, shown.height() // 2)


def test_a_reliable_open_file_check_has_its_dot_in_the_safe_colour(window: Window) -> None:
    # [0014.45]
    assert window.sidebar.open_files.text() == "Open-file check: reliable"
    assert _dot_colour(window, "open_files") == LIGHT.levels[Level.SAFE]


def test_an_open_file_check_that_is_not_reliable_has_its_dot_in_the_review_colour(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.45]
    unreliable = environment(tmp_path, zone, data_dir, open_files=UnreliableOpenFiles())
    window = make_window(qtbot, unreliable)
    assert window.sidebar.open_files.text() == "Open-file check: not reliable"
    assert _dot_colour(window, "open_files") == LIGHT.levels[Level.REVIEW]


def test_the_local_ai_line_says_its_model_and_connects_to_nothing(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.45]
    with ScriptedOllama(VERSION, TAGS) as ollama:
        env = {URL_VARIABLE: ollama.address.url, MODEL_VARIABLE: "qwen2.5:7b"}
        window = make_window(qtbot, environment(tmp_path, zone, data_dir, llm_env=env))
        assert window.sidebar.ai.text() == "AI explanations: qwen2.5:7b"
        assert _dot_colour(window, "ai") == LIGHT.secondary
        assert ollama.paths() == []


def test_the_local_ai_line_names_the_default_model_and_a_refused_setting(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.45]
    plain = make_window(qtbot, environment(tmp_path, zone, data_dir))
    assert plain.sidebar.ai.text() == "AI explanations: llama3.2"
    refused = environment(tmp_path, zone, data_dir, llm_env={MODEL_VARIABLE: "no model!"})
    window = make_window(qtbot, refused)
    assert window.sidebar.ai.text() == f"AI explanations: {MODEL_VARIABLE} is refused"
    assert _dot_colour(window, "ai") == LIGHT.secondary


def test_the_local_ai_dot_says_what_the_last_check_found(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.45]
    no_model = as_json({"models": []})
    with ScriptedOllama(VERSION, TAGS, VERSION, no_model) as ollama:
        env = {URL_VARIABLE: ollama.address.url}
        window = make_window(qtbot, environment(tmp_path, zone, data_dir, llm_env=env))
        window.settings.check_button.click()
        wait_idle(qtbot, window)
        assert _dot_colour(window, "ai") == LIGHT.levels[Level.SAFE]
        window.settings.check_button.click()
        wait_idle(qtbot, window)
        assert _dot_colour(window, "ai") == LIGHT.levels[Level.REVIEW]
    assert window.sidebar.ai.text() == "AI explanations: llama3.2"


def test_the_status_lines_in_russian_and_in_the_dark_palette(
    request: pytest.FixtureRequest, qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.45]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), language="ru")
    request.getfixturevalue("dark")
    assert window.sidebar.open_files.text() == "Открытые файлы: проверка надёжна"
    assert window.sidebar.ai.text() == "Объяснения ИИ: llama3.2"
    assert _dot_colour(window, "open_files") == DARK.levels[Level.SAFE]
    assert _dot_colour(window, "ai") == DARK.secondary
    assert [window.sidebar.text(row) for row in range(len(PAGES))] == [
        "Обзор",
        "Находки",
        "Сортировка",
        "Автозагрузка",
        "Карантин",
        "Настройки",
    ]
