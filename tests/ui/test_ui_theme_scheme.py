"""The system decides light or dark, and a change applies at once (decision 0014, items 34 and
47), unless the theme chosen is light or dark (decision 0018, item 2)."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from kresorter.ui.settings import ThemeSetting
from kresorter.ui.theme import DARK, LIGHT, Look, Palette, style_sheet


def test_the_scheme_qt_reports_decides_and_a_change_applies_at_once(
    qtbot: QtBot, qapp: QApplication
) -> None:
    # [0014.34]
    window = QWidget()
    qtbot.addWidget(window)
    hints = qapp.styleHints()
    assert hints.colorScheme() != Qt.ColorScheme.Dark  # offscreen reports none
    look = Look(window)
    assert look.parent() is window
    assert look.palette is LIGHT
    assert window.styleSheet() == style_sheet(LIGHT)

    hints.colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert look.palette is DARK
    assert window.styleSheet() == style_sheet(DARK)

    hints.colorSchemeChanged.emit(Qt.ColorScheme.Unknown)
    assert look.palette is LIGHT
    assert window.styleSheet() == style_sheet(LIGHT)

    hints.colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    hints.colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert look.palette is LIGHT
    assert window.styleSheet() == style_sheet(LIGHT)


def test_a_change_of_the_scheme_says_which_palette_applies_now(
    qtbot: QtBot, qapp: QApplication
) -> None:
    # [0014.34] [0014.47] What draws itself (icons, rows) is drawn again in the new palette.
    window = QWidget()
    qtbot.addWidget(window)
    look = Look(window)
    told: list[object] = []
    look.changed.connect(told.append)
    hints = qapp.styleHints()
    hints.colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    hints.colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert told == [DARK, LIGHT]


@pytest.mark.parametrize(("theme", "palette"), [("light", LIGHT), ("dark", DARK)])
def test_a_theme_chosen_is_its_palette_whatever_the_system_says(
    qtbot: QtBot, qapp: QApplication, theme: ThemeSetting, palette: Palette
) -> None:
    # [0018.2] A change of the system's scheme then changes nothing.
    window = QWidget()
    qtbot.addWidget(window)
    look = Look(window, theme)
    assert (look.theme, look.palette) == (theme, palette)
    assert window.styleSheet() == style_sheet(palette)
    told: list[object] = []
    look.changed.connect(told.append)
    hints = qapp.styleHints()
    for scheme in (Qt.ColorScheme.Dark, Qt.ColorScheme.Light, Qt.ColorScheme.Unknown):
        hints.colorSchemeChanged.emit(scheme)
        assert look.palette is palette
    assert told == []
    assert window.styleSheet() == style_sheet(palette)


def test_a_theme_chosen_applies_at_once_and_the_system_s_follows_its_scheme_again(
    qtbot: QtBot, qapp: QApplication
) -> None:
    # [0018.2] Back to the system's theme: the scheme the system last reported.
    window = QWidget()
    qtbot.addWidget(window)
    hints = qapp.styleHints()
    look = Look(window)
    assert look.theme == "system"
    told: list[object] = []
    look.changed.connect(told.append)

    look.choose("dark")
    assert (look.theme, look.palette) == ("dark", DARK)
    assert window.styleSheet() == style_sheet(DARK)
    hints.colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert look.palette is DARK
    look.choose("light")
    assert (look.theme, look.palette) == ("light", LIGHT)
    hints.colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert look.palette is LIGHT

    look.choose("system")
    assert (look.theme, look.palette) == ("system", DARK)
    assert window.styleSheet() == style_sheet(DARK)
    hints.colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert look.palette is LIGHT
    assert told == [DARK, LIGHT, DARK, LIGHT]
