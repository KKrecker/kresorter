"""The system decides light or dark, and a change applies at once (decision 0014, items 34 and
47)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from safeclean.ui.theme import DARK, LIGHT, Look, style_sheet


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
