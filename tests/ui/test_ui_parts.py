"""The parts the pages are made of: heads, notes, cards, chips, links, badges, check boxes and
the lists' rows (decision 0014, items 46 and 47)."""

import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFont, QIcon, QImage, QStandardItem, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListView, QPushButton, QTreeView, QWidget
from pytestqt.qtbot import QtBot

from safeclean.analysis.score import Level
from safeclean.ui.parts import (
    BADGE,
    BADGE_HEIGHT,
    CHECK,
    EMPHASIS,
    GRID,
    QUIET,
    ROW_HEIGHT,
    SECONDARY,
    CheckBox,
    Choice,
    Head,
    Icon,
    Note,
    RowDelegate,
    SearchField,
    badge,
    badge_colours,
    bar,
    button,
    card,
    cell_colours,
    check_colours,
    chip,
    divider,
    dot,
    hbox,
    link,
    page,
    rows,
    vbox,
)
from safeclean.ui.theme import DARK, LIGHT, Look, Palette
from support.drawn import drawn_in, inked_in

CHECKED, PARTLY, UNCHECKED = (
    Qt.CheckState.Checked,
    Qt.CheckState.PartiallyChecked,
    Qt.CheckState.Unchecked,
)


@pytest.fixture
def holder(qtbot: QtBot) -> QWidget:
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def look(holder: QWidget) -> Look:
    return Look(holder)


def _shown(qtbot: QtBot, widget: QWidget) -> None:
    widget.show()
    qtbot.waitExposed(widget)


def _colour(image: QImage, x: int, y: int) -> str:
    return image.pixelColor(x, y).name().upper()


def _dark(qapp: QApplication) -> None:
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)


def _light(qapp: QApplication) -> None:
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)


# --- layouts and heads [0014.46] -----------------------------------------------------------------


def test_a_layout_s_margins_and_spacing_are_always_given(holder: QWidget) -> None:
    # [0014.46]
    made = [
        vbox(),
        hbox(),
        vbox(holder, margins=(4, 8, 12, 16), spacing=24),
        hbox(QWidget(holder), margins=(32, 32, 32, 32), spacing=40),
    ]
    assert [layout.spacing() for layout in made] == [0, 0, 24, 40]
    assert [layout.contentsMargins().top() for layout in made] == [0, 0, 8, 32]
    assert holder.layout() is made[2]
    assert {0, 4, 8, 12, 16, 20, 24, 32, 40} == GRID


def test_a_head_has_its_title_what_the_page_does_and_its_controls_at_the_right(
    qtbot: QtBot, holder: QWidget, look: Look
) -> None:
    # [0014.46]
    refresh = button(look, "Refresh", icon="refresh-cw")
    head = Head("Quarantine", "Files moved here can be put back.", refresh)
    layout = page(holder, head)
    holder.resize(900, 300)
    _shown(qtbot, holder)

    assert (head.title.text(), head.subtitle.text()) == (
        "Quarantine",
        "Files moved here can be put back.",
    )
    assert (head.title.font().pixelSize(), head.title.font().weight()) == (
        24,
        QFont.Weight.DemiBold,
    )
    assert head.subtitle.palette().color(head.subtitle.foregroundRole()).name().upper() == (
        LIGHT.secondary
    )
    assert head.controls == (refresh,)
    assert refresh.geometry().left() > head.title.geometry().right()
    assert refresh.mapTo(holder, QPoint(0, 0)).x() + refresh.width() == holder.width() - 32
    margins = layout.contentsMargins()
    assert (margins.left(), margins.top(), margins.right()) == (32, 32, 32)
    first = layout.itemAt(0)
    assert first is not None
    assert first.widget() is head
    assert head.mapTo(holder, QPoint(0, 0)) == QPoint(32, 32)


def test_a_head_without_controls(qtbot: QtBot, holder: QWidget) -> None:
    # [0014.46]
    head = Head("Settings", "What the window remembers.")
    page(holder, head)
    _shown(qtbot, holder)
    assert head.controls == ()
    assert head.title.isVisible()


# --- notes [0014.47] -----------------------------------------------------------------------------


def test_a_note_with_nothing_to_say_takes_no_room(qtbot: QtBot, holder: QWidget) -> None:
    # [0014.47]
    above, note = Note(holder, "Always"), Note(holder, role="secondary")
    layout = vbox(holder, spacing=16)
    layout.addWidget(above)
    layout.addWidget(note)
    _shown(qtbot, holder)
    empty = layout.sizeHint().height()
    assert note.isHidden()
    assert note.property("role") == "secondary"
    assert above.property("role") is None

    note.setText("Moved 2 files.")
    assert note.isVisible()
    assert layout.sizeHint().height() > empty + 16
    note.clear()
    assert note.isHidden()
    assert note.text() == ""
    assert layout.sizeHint().height() == empty


def test_a_note_never_opens_a_window_of_its_own(qtbot: QtBot, holder: QWidget) -> None:
    # [0014.47] Its parent is given: a text before it is laid out shows it with its parent.
    note = Note(holder)
    note.setText("Scanning")
    assert note.parentWidget() is holder
    assert not note.isWindow()
    assert not note.isVisible()
    _shown(qtbot, holder)
    assert note.isVisible()


# --- cards, dividers, dots, badges, buttons, chips, links [0014.47] ------------------------------


def test_cards_dividers_dots_and_badges_carry_the_properties_of_their_rules() -> None:
    # [0014.47]
    plain, inside = card()
    surface, _ = card(surface=True)
    margins = inside.contentsMargins()
    assert (plain.property("role"), plain.property("tone")) == ("card", None)
    assert surface.property("tone") == "surface"
    assert (margins.left(), margins.top(), inside.spacing()) == (24, 24, 8)
    assert inside.parentWidget() is plain
    line = divider()
    assert (line.property("role"), line.maximumHeight(), line.minimumHeight()) == ("divider", 1, 1)
    shown = dot("safe")
    assert (shown.property("dot"), shown.width(), shown.height()) == ("safe", 8, 8)
    pill = badge("Cannot be undone", "danger")
    assert (pill.text(), pill.property("badge")) == ("Cannot be undone", "danger")
    assert pill.minimumHeight() == pill.maximumHeight() == BADGE_HEIGHT == 20


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_a_badge_is_a_level_s_or_the_danger_one(palette: Palette) -> None:
    # [0014.47]
    assert badge_colours("danger", palette) == palette.danger_badge
    assert [badge_colours(level.value, palette) for level in Level] == [
        palette.badges[level] for level in Level
    ]


def test_buttons_chips_and_links(qtbot: QtBot, holder: QWidget, look: Look) -> None:
    # [0014.47]
    plain = button(look, "Check")
    primary = button(look, "Scan", role="primary", icon="refresh-cw")
    danger = button(look, "Delete permanently", role="danger")
    on = chip(look, "Safe", checkable=True)
    folder = chip(look, "~/Downloads", icon="folder")
    more = link("Add folder")
    layout = vbox(holder, spacing=8)
    for made in (plain, primary, danger, on, folder, more):
        layout.addWidget(made)
    _shown(qtbot, holder)

    assert [made.property("role") for made in (plain, primary, danger, on, folder, more)] == [
        None,
        "primary",
        "danger",
        "chip",
        "chip",
        "link",
    ]
    assert plain.icon().isNull()
    assert not primary.icon().isNull()
    assert not folder.icon().isNull()
    assert (on.isCheckable(), folder.isCheckable()) == (True, False)
    assert more.isFlat()
    assert more.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert all(made.height() >= 36 for made in (plain, primary, danger, on, folder))


def test_a_bar_across_a_page_s_bottom() -> None:
    # [0014.49]
    frame, inside = bar()
    margins = inside.contentsMargins()
    assert frame.property("role") == "bar"
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (32, 12, 32, 12)
    assert inside.spacing() == 16
    assert inside.parentWidget() is frame


def test_a_search_field_is_named_by_its_placeholder_its_icon_in_secondary_text(
    qapp: QApplication, look: Look
) -> None:
    # [0014.49] The icon's button says what the field is for, as the field does.
    field = SearchField(look, "Search the paths")
    assert field.placeholderText() == field.accessibleName() == "Search the paths"
    assert field.glass.text() == "Search the paths"
    for palette in (LIGHT, DARK):
        if palette is DARK:
            _dark(qapp)
        shown = field.glass.icon().pixmap(QSize(16, 16), 2.0).toImage()
        assert inked_in(shown, palette.secondary)
    _light(qapp)


def _icon(made: QPushButton, mode: QIcon.Mode = QIcon.Mode.Normal) -> QImage:
    return made.icon().pixmap(QSize(16, 16), 2.0, mode).toImage()


def test_a_button_s_icon_is_drawn_in_its_text_s_colour_light_or_dark(
    qapp: QApplication, look: Look
) -> None:
    # [0014.47]
    primary = button(look, "Scan", role="primary", icon="refresh-cw")
    danger = button(look, "Delete", role="danger", icon="x")
    plain = button(look, "Refresh", icon="refresh-cw")
    for palette in (LIGHT, DARK):
        if palette is DARK:
            _dark(qapp)
        assert inked_in(_icon(primary), palette.primary_text)
        assert inked_in(_icon(danger), palette.primary_text)
        assert inked_in(_icon(plain), palette.text)
        assert inked_in(_icon(plain, QIcon.Mode.Disabled), palette.secondary)
    _light(qapp)


def test_an_icon_on_its_tile_in_the_palette_s_colours(
    qtbot: QtBot, qapp: QApplication, holder: QWidget, look: Look
) -> None:
    # [0014.47]
    mark = Icon(
        look, "shield-check", lambda p: p.primary_text, size=16, tile=lambda p: p.accent, side=28
    )
    bare = Icon(look, "folder", lambda p: p.secondary)
    layout = hbox(holder, spacing=8)
    layout.addWidget(mark)
    layout.addWidget(bare)
    _shown(qtbot, holder)
    assert (mark.name, mark.width(), bare.width()) == ("shield-check", 28, 16)
    assert mark.colours() == (LIGHT.primary_text, LIGHT.accent)
    assert bare.colours() == (LIGHT.secondary, None)
    drawn = mark.grab().toImage()
    assert _colour(drawn, 3, 14) == LIGHT.accent
    assert drawn_in(bare.grab().toImage(), LIGHT.secondary, LIGHT.canvas)
    _dark(qapp)
    assert mark.colours() == (DARK.primary_text, DARK.accent)
    assert _colour(mark.grab().toImage(), 3, 14) == DARK.accent
    _light(qapp)


# --- check boxes [0014.47] -----------------------------------------------------------------------


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_a_check_box_is_on_the_accent_when_checked(palette: Palette) -> None:
    # [0014.47]
    assert check_colours(CHECKED, palette) == (palette.accent, palette.accent, palette.primary_text)
    assert check_colours(PARTLY, palette) == (palette.accent, palette.accent, palette.primary_text)
    assert check_colours(UNCHECKED, palette) == (palette.canvas, palette.secondary, None)


def test_the_window_s_check_box_is_drawn_as_the_lists_draw_theirs(
    qtbot: QtBot, holder: QWidget, look: Look
) -> None:
    # [0014.47] On the canvas when unchecked, on the accent when checked; the focus a ring of
    # the accent around the box.
    box, other = CheckBox(look, "Safe"), CheckBox(look, "Review")
    layout = vbox(holder, spacing=8)
    layout.addWidget(box)
    layout.addWidget(other)
    _shown(qtbot, holder)
    assert box.height() >= 36
    assert box.minimumSizeHint() == box.sizeHint()
    inside = box.box()
    middle = inside.center().y()
    assert _colour(box.grab().toImage(), inside.center().x(), middle) == LIGHT.canvas
    QTest.mouseClick(box, Qt.MouseButton.LeftButton, pos=QPoint(box.width() - 2, middle))
    assert box.isChecked()  # its text is part of it
    assert _colour(box.grab().toImage(), inside.left() + 1, middle) == LIGHT.accent
    box.setEnabled(False)
    assert not box.grab().isNull()

    assert _colour(other.grab().toImage(), 0, middle) != LIGHT.accent
    with qtbot.waitActive(holder):
        holder.activateWindow()
    other.setFocus()
    assert other.hasFocus()
    assert _colour(other.grab().toImage(), 0, middle) == LIGHT.accent


def test_a_choice_draws_its_chevron(qtbot: QtBot, holder: QWidget, look: Look) -> None:
    # [0014.47]
    choice = Choice(look)
    choice.addItems(["English", "Русский"])
    layout = vbox(holder)
    layout.addWidget(choice)
    holder.setStyleSheet(holder.styleSheet())
    _shown(qtbot, holder)
    drawn = choice.grab().toImage()
    chevron = drawn.copy(QRect(choice.width() - 24, (choice.height() - 16) // 2, 16, 16))
    assert drawn_in(chevron, LIGHT.secondary, LIGHT.canvas)
    assert choice.height() >= 36


# --- lists [0014.47] -----------------------------------------------------------------------------


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_a_cell_s_colours(palette: Palette) -> None:
    # [0014.47] A selected row lies on the accent's tint; quiet and disabled text is secondary.
    assert cell_colours(palette) == (None, palette.text)
    assert cell_colours(palette, selected=True) == (palette.selection, palette.text)
    assert cell_colours(palette, quiet=True) == (None, palette.secondary)
    assert cell_colours(palette, enabled=False) == (None, palette.secondary)


def _item(text: str, **roles: object) -> QStandardItem:
    item = QStandardItem(text)
    for role, value in roles.items():
        item.setData(
            value, {"second": SECONDARY, "strong": EMPHASIS, "quiet": QUIET, "badge": BADGE}[role]
        )
    return item


def _model() -> QStandardItemModel:
    model = QStandardItemModel(0, 3)
    model.setHorizontalHeaderLabels(["Name", "Size", "Level"])
    first = _item("Browser cache", second="2,404 files · chromium-cache", strong=True)
    first.setCheckable(True)
    first.setCheckState(CHECKED)
    size = _item("1.12 GB", strong=True)
    size.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    model.appendRow([first, size, _item("Safe", badge="safe")])
    partly = _item("Tool caches", second="1,212 files")
    partly.setCheckable(True)
    partly.setCheckState(PARTLY)
    model.appendRow(
        [partly, _item("486 MB", quiet=True), _item("Cannot be undone", badge="danger")]
    )
    left = _item("serde-1.0.197.crate")
    left.setCheckable(True)
    left.setCheckState(UNCHECKED)
    model.appendRow([left, _item("2.3 MB"), _item("")])
    kept = _item("kept copy")
    kept.setEnabled(False)
    kept.setCheckable(True)
    model.appendRow([kept, _item(""), _item("")])
    return model


@pytest.fixture
def listed(qtbot: QtBot, holder: QWidget, look: Look) -> QTreeView:
    view = QTreeView()
    rows(view, look)
    view.setModel(_model())
    view.setRootIsDecorated(False)
    layout = vbox(holder)
    layout.addWidget(view)
    holder.resize(700, 400)
    _shown(qtbot, holder)
    for column in range(3):
        view.resizeColumnToContents(column)
    return view


def _cell(view: QTreeView, row: int, column: int = 0) -> QRect:
    model = view.model()
    return view.visualRect(model.index(row, column))


def _box(view: QTreeView, row: int) -> QRect:
    rect = _cell(view, row)
    return QRect(rect.left() + 12, rect.center().y() - CHECK // 2 + 1, CHECK, CHECK)


def test_lists_are_drawn_by_the_row_delegate_without_a_frame_or_alternate_rows(
    listed: QTreeView, look: Look
) -> None:
    # [0014.47]
    assert isinstance(listed.itemDelegate(), RowDelegate)
    assert not listed.alternatingRowColors()
    assert listed.frameShape() == listed.Shape.NoFrame
    assert listed.header().font().capitalization() == QFont.Capitalization.AllUppercase
    plain = rows(QListView(), look)
    assert isinstance(plain.itemDelegate(), RowDelegate)


def test_rows_are_44_px_high_or_more_a_name_and_under_it_a_line_of_secondary_text(
    listed: QTreeView,
) -> None:
    # [0014.47]
    heights = [_cell(listed, row).height() for row in range(4)]
    assert all(height >= ROW_HEIGHT for height in heights)
    assert heights[0] > heights[2] == ROW_HEIGHT  # two lines, one line
    assert _cell(listed, 0, 2).width() >= 24 + 16  # the badge's padding


def test_a_row_is_divided_by_the_border_colour_and_selected_on_the_accent_s_tint(
    listed: QTreeView,
) -> None:
    # [0014.47]
    listed.setCurrentIndex(listed.model().index(2, 0))
    drawn = listed.viewport().grab().toImage()
    for row in range(3):
        rect = _cell(listed, row)
        assert _colour(drawn, rect.left() + 4, rect.bottom()) == LIGHT.border
    chosen, other = _cell(listed, 2), _cell(listed, 0)
    assert _colour(drawn, chosen.left() + 4, chosen.top() + 2) == LIGHT.selection
    assert _colour(drawn, other.left() + 4, other.top() + 2) == LIGHT.canvas
    pill = _cell(listed, 0, 2)
    assert (
        _colour(drawn, pill.left() + 12 + 3, pill.center().y() + 1)
        == LIGHT.badges[Level.SAFE].background
    )
    danger = _cell(listed, 1, 2)
    assert (
        _colour(drawn, danger.left() + 12 + 3, danger.center().y() + 1)
        == LIGHT.danger_badge.background
    )


def test_check_boxes_in_a_list_are_on_the_accent_when_checked(listed: QTreeView) -> None:
    # [0014.47]
    drawn = listed.viewport().grab().toImage()
    checked, partly, unchecked = (_box(listed, row) for row in range(3))
    assert _colour(drawn, checked.left() + 1, checked.center().y()) == LIGHT.accent
    assert _colour(drawn, partly.left() + 1, partly.center().y()) == LIGHT.accent
    assert _colour(drawn, unchecked.center().x(), unchecked.center().y()) == LIGHT.canvas


def test_a_click_on_a_check_box_turns_it_and_nothing_else_does(
    listed: QTreeView,
) -> None:
    # [0014.47]
    model = listed.model()
    viewport = listed.viewport()

    def state(row: int) -> object:
        return model.index(row, 0).data(Qt.ItemDataRole.CheckStateRole)

    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=_box(listed, 2).center())
    assert state(2) == CHECKED.value
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=_box(listed, 2).center())
    assert state(2) == UNCHECKED.value
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=_box(listed, 1).center())
    assert state(1) == CHECKED.value  # partly checked: checked
    beside = _cell(listed, 2).center()
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=beside)
    assert state(2) == UNCHECKED.value
    assert listed.currentIndex().row() == 2  # a click beside it selects the row
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=_cell(listed, 2, 1).center())
    assert state(2) == UNCHECKED.value  # no check box in that cell
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=_box(listed, 3).center())
    assert state(3) == UNCHECKED.value  # disabled
    listed.setCurrentIndex(model.index(2, 0))
    QTest.keyClick(listed, Qt.Key.Key_Space)
    assert state(2) == CHECKED.value  # the keys are Qt's own


def test_lists_are_drawn_in_the_dark_palette_too(qapp: QApplication, listed: QTreeView) -> None:
    # [0014.47]
    _dark(qapp)
    drawn = listed.viewport().grab().toImage()
    rect = _cell(listed, 2)
    assert _colour(drawn, rect.left() + 4, rect.bottom()) == DARK.border
    checked = _box(listed, 0)
    assert _colour(drawn, checked.left() + 1, checked.center().y()) == DARK.accent
    _light(qapp)
