"""Every page in the prototype's look: its head, the grid of its margins and spacings, and the
parts it is made of (decision 0014, items 46 and 47)."""

from pathlib import Path

import pytest
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QTreeView,
    QWidget,
)
from pytestqt.qtbot import QtBot

from safeclean.ui.i18n import Language
from safeclean.ui.parts import (
    BADGE_HEIGHT,
    GRID,
    PAGE_MARGIN,
    CheckBox,
    Choice,
    Head,
    RowDelegate,
)
from safeclean.ui.sidebar import NavDelegate
from safeclean.ui.window import PAGES, Window
from support.window import environment, junk_tree, make_window, scanned

_MINIMUM = 36  # px: a chip's, a field's and a button's height


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path) -> Window:
    return make_window(qtbot, environment(tmp_path, zone, data_dir))


@pytest.fixture
def scanned_window(qtbot: QtBot, window: Window, zone: Path) -> Window:
    junk_tree(zone)
    scanned(qtbot, window)
    return window


def _central(window: Window) -> QWidget:
    central = window.centralWidget()
    assert central is not None
    return central


def _head(window: Window, name: str) -> Head:
    layout = window.page(name).layout()
    assert layout is not None
    item = layout.itemAt(0)
    assert item is not None
    head = item.widget()
    assert isinstance(head, Head)
    return head


def _inside_a_combo_box(widget: QWidget) -> bool:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QComboBox):
            return True
        parent = parent.parentWidget()
    return False


def _shown(window: Window, name: str) -> list[QWidget]:
    """The widgets of the page ``name`` that are visible once it is open."""
    window.show_page(name)
    return [
        widget
        for widget in window.page(name).findChildren(QWidget)
        if widget.isVisible() and not _inside_a_combo_box(widget)
    ]


# --- a page's head [0014.46] ---------------------------------------------------------------------


@pytest.mark.parametrize("language", ["en", "ru"])
def test_every_page_starts_with_its_title_and_what_it_does(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, language: Language
) -> None:
    # [0014.46]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), language=language)
    text = window.translator.text
    for name in PAGES:
        head = _head(window, name)
        assert head.title.text() == text(f"page.{name}")
        assert head.subtitle.text() == text(f"head.{name}")
        assert head.subtitle.text() != head.title.text()


def test_a_title_is_24_px_semibold_and_what_it_does_is_secondary_text(window: Window) -> None:
    # [0014.46]
    palette = window.look.palette
    for name in PAGES:
        window.show_page(name)
        head = _head(window, name)
        assert head.title.font().pixelSize() == 24
        assert head.title.font().weight() == QFont.Weight.DemiBold
        assert head.title.palette().color(QPalette.ColorRole.WindowText).name().upper() == (
            palette.text
        )
        shown = head.subtitle.palette().color(QPalette.ColorRole.WindowText).name().upper()
        assert shown == palette.secondary


def test_a_page_has_margins_of_32_px_at_its_sides_and_its_top(window: Window) -> None:
    # [0014.46]
    assert PAGE_MARGIN == 32
    for name in PAGES:
        layout = window.page(name).layout()
        assert layout is not None
        margins = layout.contentsMargins()
        assert (margins.left(), margins.top(), margins.right()) == (32, 32, 32)
        window.show_page(name)
        assert _head(window, name).geometry().topLeft().toTuple() == (32, 32)


def test_the_page_s_own_controls_sit_at_the_right_of_its_title(window: Window) -> None:
    # [0014.46] Findings' Rescan and Autostart's search come with their pages (items 49, 53).
    for name, controls in (
        ("quarantine", (window.quarantine.refresh_button,)),
        ("autostart", (window.autostart.refresh_button,)),
        ("overview", ()),
        ("settings", ()),
    ):
        window.show_page(name)
        head = _head(window, name)
        assert head.controls == controls
        for control in controls:
            assert control.isVisible()
            assert control.parentWidget() is head
            assert control.geometry().left() > head.title.geometry().right()
            assert control.geometry().top() == head.title.geometry().top()
            assert control.geometry().right() == head.width() - 1


def _spacings(layout: QLayout) -> list[int]:
    if isinstance(layout, QGridLayout | QFormLayout):
        return [layout.horizontalSpacing(), layout.verticalSpacing()]
    return [layout.spacing()]


def _layouts(layout: QLayout | None) -> list[QLayout]:
    """``layout`` and the layouts in it."""
    if layout is None:
        return []
    found = [layout]
    for index in range(layout.count()):
        item = layout.itemAt(index)
        found += _layouts(None if item is None else item.layout())
    return found


def _off_the_grid(window: Window) -> list[tuple[str, list[int]]]:
    """The layouts of the window's widgets (a combo box's popup is Qt's) off the grid."""
    central = _central(window)
    owners = [central, *central.findChildren(QWidget)]
    found = []
    for owner in owners:
        if _inside_a_combo_box(owner):
            continue
        for layout in _layouts(owner.layout()):
            margins = layout.contentsMargins()
            values = [margins.left(), margins.top(), margins.right(), margins.bottom()]
            values += _spacings(layout)
            if not set(values) <= GRID:
                found.append((f"{type(layout).__name__} of {owner!r}", values))
    return found


def test_every_margin_and_spacing_is_on_the_grid(window: Window) -> None:
    # [0014.46]
    assert sorted(GRID) == [0, 4, 8, 12, 16, 24, 32, 40]
    assert _off_the_grid(window) == []


def test_every_margin_and_spacing_is_on_the_grid_after_a_scan(scanned_window: Window) -> None:
    # [0014.46]
    assert _off_the_grid(scanned_window) == []


# --- the parts [0014.47] -------------------------------------------------------------------------


def test_every_list_draws_its_rows_with_the_row_delegate_and_no_alternate_rows(
    window: Window,
) -> None:
    # [0014.47]
    views = [
        view
        for view in _central(window).findChildren(QAbstractItemView)
        if not _inside_a_combo_box(view) and not isinstance(view, QHeaderView)
    ]
    assert len(views) >= 6
    for view in views:
        delegate = view.itemDelegate()
        if view.property("role") == "nav":
            assert isinstance(delegate, NavDelegate)
        else:
            assert isinstance(delegate, RowDelegate), view
        assert not view.alternatingRowColors()
        if isinstance(view, QTreeView):
            assert view.header().font().capitalization() == QFont.Capitalization.AllUppercase


def test_every_check_box_and_every_choice_is_drawn_by_the_parts(window: Window) -> None:
    # [0014.47]
    central = _central(window)
    boxes = central.findChildren(QCheckBox)
    choices = central.findChildren(QComboBox)
    assert boxes
    assert choices
    assert all(isinstance(box, CheckBox) for box in boxes)
    assert all(isinstance(choice, Choice) for choice in choices)


@pytest.mark.parametrize("name", PAGES)
def test_chips_fields_and_buttons_are_at_least_36_px_high(
    scanned_window: Window, name: str
) -> None:
    # [0014.47] A link is text, not a button to the eye.
    low = [
        widget
        for widget in _shown(scanned_window, name)
        if isinstance(widget, QPushButton | QLineEdit | QComboBox)
        and widget.property("role") != "link"
        and widget.height() < _MINIMUM
    ]
    assert low == []


@pytest.mark.parametrize("name", PAGES)
def test_a_label_with_nothing_to_say_takes_no_room(window: Window, name: str) -> None:
    # [0014.47]
    empty = [
        widget
        for widget in _shown(window, name)
        if isinstance(widget, QLabel) and not widget.text() and widget.pixmap().isNull()
    ]
    assert empty == []


@pytest.mark.parametrize("name", PAGES)
def test_a_label_with_nothing_to_say_takes_no_room_after_a_scan(
    scanned_window: Window, name: str
) -> None:
    # [0014.47]
    empty = [
        widget
        for widget in _shown(scanned_window, name)
        if isinstance(widget, QLabel) and not widget.text() and widget.pixmap().isNull()
    ]
    assert empty == []


def test_badges_are_pills_20_px_high(scanned_window: Window) -> None:
    # [0014.47]
    assert BADGE_HEIGHT == 20
    badges = [
        widget
        for widget in _shown(scanned_window, "overview")
        if isinstance(widget, QLabel) and widget.property("badge")
    ]
    assert len(badges) == 3
    assert all(badge.height() == BADGE_HEIGHT for badge in badges)
