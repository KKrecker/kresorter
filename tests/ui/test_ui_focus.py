"""A list is ringed only when the keyboard focused it (decision 0018, item 23).

A list or tree focused by Tab, Backtab or a shortcut has the accent border until it loses
focus; one focused by a click has none, its selected row saying where it is. Buttons, fields
and choices keep their ring. What is drawn is read from the border's pixels.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QAbstractItemView, QApplication, QTreeWidget
from pytestqt.qtbot import QtBot

from kresorter.ui.parts import KEYBOARD_FOCUS
from kresorter.ui.theme import LIGHT, style_sheet
from kresorter.ui.window import Window
from support.drawn import drawn_in
from support.window import environment, make_window

Reason = Qt.FocusReason


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path) -> Window:
    made = make_window(qtbot, environment(tmp_path, zone, data_dir))
    made.show_page("findings")
    return made


def _lists(window: Window) -> list[QTreeWidget]:
    """The window's lists, all trees: a header and a choice's popup are no list of its own."""
    return window.findChildren(QTreeWidget)


def _focused(qtbot: QtBot, view: QAbstractItemView, reason: Qt.FocusReason) -> None:
    view.setFocus(reason)
    qtbot.waitUntil(view.hasFocus)
    QApplication.sendPostedEvents()


def _ringed(view: QAbstractItemView) -> bool:
    """The view's top edge drawn in the accent, on the canvas."""
    view.repaint()
    image = view.grab().toImage()
    edge = image.copy(image.width() // 4, 0, image.width() // 2, 1)
    return drawn_in(edge, LIGHT.accent, LIGHT.canvas, within=8)


def test_every_list_of_the_window_can_be_ringed_from_the_keyboard(window: Window) -> None:
    # [0018.23] Every list and tree of the window follows the rule; the sidebar's pages are
    # a list of their own, which marks the current page instead.
    views = _lists(window)
    assert len(views) == 5
    assert all(view.property(KEYBOARD_FOCUS) is not None for view in views)


@pytest.mark.parametrize("reason", [Reason.TabFocusReason, Reason.BacktabFocusReason])
def test_a_list_focused_by_the_keyboard_is_ringed(
    qtbot: QtBot, window: Window, reason: Qt.FocusReason
) -> None:
    # [0018.23]
    tree = window.findings.tree
    _focused(qtbot, tree, reason)
    assert tree.property(KEYBOARD_FOCUS) is True
    assert _ringed(tree)


def test_a_list_focused_by_a_shortcut_is_ringed(qtbot: QtBot, window: Window) -> None:
    # [0018.23]
    tree = window.findings.tree
    _focused(qtbot, tree, Reason.ShortcutFocusReason)
    assert tree.property(KEYBOARD_FOCUS) is True


def test_a_list_focused_by_a_click_is_not_ringed(qtbot: QtBot, window: Window) -> None:
    # [0018.23] The blue ring of the owner's screenshot (the autostart list, clicked).
    tree = window.findings.tree
    _focused(qtbot, tree, Reason.MouseFocusReason)
    assert tree.property(KEYBOARD_FOCUS) is False
    assert not _ringed(tree)


def test_a_click_after_the_keyboard_takes_the_ring_away(qtbot: QtBot, window: Window) -> None:
    # [0018.23]
    tree = window.findings.tree
    _focused(qtbot, tree, Reason.TabFocusReason)
    window.findings.search.setFocus(Reason.MouseFocusReason)
    qtbot.waitUntil(lambda: not tree.hasFocus())
    _focused(qtbot, tree, Reason.MouseFocusReason)
    assert tree.property(KEYBOARD_FOCUS) is False


def test_losing_focus_takes_the_ring_away(qtbot: QtBot, window: Window) -> None:
    # [0018.23]
    tree = window.findings.tree
    _focused(qtbot, tree, Reason.TabFocusReason)
    window.findings.search.setFocus(Reason.TabFocusReason)
    qtbot.waitUntil(lambda: not tree.hasFocus())
    assert tree.property(KEYBOARD_FOCUS) is False
    assert not _ringed(tree)


def test_the_window_losing_and_finding_its_focus_keeps_the_ring(
    qtbot: QtBot, window: Window
) -> None:
    # [0018.23] Another window activated, then this one again: the focus comes back as it was.
    tree = window.findings.tree
    _focused(qtbot, tree, Reason.TabFocusReason)
    QApplication.sendEvent(tree, _focus_event(out=True, reason=Reason.ActiveWindowFocusReason))
    assert tree.property(KEYBOARD_FOCUS) is True
    QApplication.sendEvent(tree, _focus_event(out=False, reason=Reason.ActiveWindowFocusReason))
    assert tree.property(KEYBOARD_FOCUS) is True


def _focus_event(*, out: bool, reason: Qt.FocusReason) -> QFocusEvent:
    kind = QEvent.Type.FocusOut if out else QEvent.Type.FocusIn
    return QFocusEvent(kind, reason)


def test_the_style_sheet_rings_a_list_only_with_the_keyboard_s_mark() -> None:
    # [0018.23] Buttons, fields and choices keep their ring.
    sheet = style_sheet(LIGHT)
    ring = f"border: 1px solid {LIGHT.accent};"
    assert f'QAbstractItemView[{KEYBOARD_FOCUS}="true"]:focus {{ {ring} }}' in sheet
    focus = next(line for line in sheet.splitlines() if line.startswith("QPushButton:focus"))
    assert "QAbstractItemView:focus" not in focus
    assert "QLineEdit:focus" in focus
    assert "QComboBox:focus" in focus
