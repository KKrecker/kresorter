"""The parts the pages are made of (decision 0014, items 46 and 47).

``head`` starts a page: its title, one line of secondary text, and the page's own controls at
the right. ``page`` lays a page out with the margins of item 46; ``vbox`` and ``hbox`` are
layouts whose margins and spacing are always given. A ``Note`` takes no room while it has
nothing to say. Cards, chips, links, badges, dots and dividers carry the property their rule
of ``ui.theme`` selects. Lists are drawn by ``RowDelegate``: rows at least 44 px high, a name
and under it, when the row has one, a line of secondary text (``SECONDARY``), a divider in the
border colour, the selection on the accent's tint, and check boxes drawn on the accent when
checked (``paint_check``, which ``CheckBox`` shares). Every colour comes from the window's
palette, read from its ``Look`` when a part is drawn.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QFontMetricsF,
    QIcon,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from safeclean.analysis.score import Level
from safeclean.ui import icons
from safeclean.ui.theme import Badge, Look, Palette

__all__ = [
    "BADGE",
    "BADGE_HEIGHT",
    "CHECK",
    "EMPHASIS",
    "GRID",
    "INITIAL",
    "PAGE_MARGIN",
    "QUIET",
    "ROW_HEIGHT",
    "SECONDARY",
    "SWITCH_SIZE",
    "TILE",
    "CheckBox",
    "Choice",
    "Field",
    "Head",
    "Icon",
    "Note",
    "RowDelegate",
    "Switch",
    "badge",
    "badge_colours",
    "bar",
    "button",
    "card",
    "cell_colours",
    "check_colours",
    "chip",
    "divider",
    "dot",
    "hbox",
    "link",
    "mark",
    "page",
    "paint_check",
    "rows",
    "secondary_ink",
    "shares",
    "surface2_tile",
    "text_ink",
    "vbox",
]

GRID = frozenset({0, 4, 8, 12, 16, 20, 24, 32, 40})  # every margin and spacing of a layout
PAGE_MARGIN = 32
ROW_HEIGHT = 44
CHECK = 16  # a check box's side
BADGE_HEIGHT = 20

_ROLE = Qt.ItemDataRole.UserRole + 32
SECONDARY = _ROLE  # a row's line of secondary text, under its name
EMPHASIS = _ROLE + 1  # a cell's text in semibold
QUIET = _ROLE + 2  # a cell's text in secondary text
BADGE = _ROLE + 3  # a cell drawn as a badge: a level's value, "advisory" or "danger"
INITIAL = _ROLE + 4  # a cell's tile at its left, with an initial on it
TILE = 32  # px: the side of a cell's tile
SWITCH_SIZE = QSize(40, 24)  # a switch: its track and, around it, its focus ring

_PAD = 12  # a cell's padding at its sides
_LINE_GAP = 2
_SMALL = 12  # px: the line of secondary text, a badge


def vbox(
    parent: QWidget | None = None,
    *,
    margins: tuple[int, int, int, int] = (0, 0, 0, 0),
    spacing: int = 0,
) -> QVBoxLayout:
    layout = QVBoxLayout(parent) if parent is not None else QVBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def hbox(
    parent: QWidget | None = None,
    *,
    margins: tuple[int, int, int, int] = (0, 0, 0, 0),
    spacing: int = 0,
) -> QHBoxLayout:
    layout = QHBoxLayout(parent) if parent is not None else QHBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


class Note(QLabel):
    """A label that takes no room while it has nothing to say: hidden while its text is empty.
    It is made with its parent, so that showing it never opens a window of its own."""

    def __init__(self, parent: QWidget, text: str = "", *, role: str = "") -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if role:
            self.setProperty("role", role)
        self.setText(text)

    def setText(self, text: str, /) -> None:
        super().setText(text)
        self.setHidden(not text)

    def clear(self) -> None:
        self.setText("")


class Head(QWidget):
    """A page's head: its title and what it does under it; its controls at the right."""

    def __init__(self, title: str, subtitle: str, *controls: QWidget) -> None:
        super().__init__()
        self.setObjectName("head")
        self.title = QLabel(title)
        self.title.setObjectName("title")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("subtitle")
        self.subtitle.setWordWrap(True)
        self.controls = controls
        words = vbox(spacing=4)
        words.addWidget(self.title)
        words.addWidget(self.subtitle)
        layout = hbox(self, spacing=16)
        layout.addLayout(words, 1)
        for control in controls:
            layout.addWidget(control, 0, Qt.AlignmentFlag.AlignTop)


def page(widget: QWidget, head: Head) -> QVBoxLayout:
    """``widget``'s layout: margins of 32 px, its head first."""
    margin = PAGE_MARGIN
    layout = vbox(widget, margins=(margin, margin, margin, margin), spacing=16)
    layout.addWidget(head)
    return layout


def card(*, surface: bool = False) -> tuple[QFrame, QVBoxLayout]:
    """A card (on the canvas, or on surface) and its layout."""
    frame = QFrame()
    frame.setProperty("role", "card")
    if surface:
        frame.setProperty("tone", "surface")
    return frame, vbox(frame, margins=(24, 24, 24, 24), spacing=8)


def shares(widget: QWidget) -> None:
    """A card of a row takes its share of the row, whatever it has to say: a long text wraps
    or is cut rather than widening its card."""
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)


def text_ink(palette: Palette) -> str:
    """An icon in the text's colour."""
    return palette.text


def secondary_ink(palette: Palette) -> str:
    """An icon in secondary text's colour."""
    return palette.secondary


def surface2_tile(palette: Palette) -> str:
    """An icon's tile, on surface 2."""
    return palette.surface2


def bar() -> tuple[QFrame, QHBoxLayout]:
    """The bar at a page's bottom, across its width with a border above it, and its layout."""
    frame = QFrame()
    frame.setProperty("role", "bar")
    return frame, hbox(frame, margins=(PAGE_MARGIN, 12, PAGE_MARGIN, 12), spacing=16)


def divider() -> QFrame:
    line = QFrame()
    line.setProperty("role", "divider")
    line.setFixedHeight(1)
    return line


def dot(kind: str) -> QFrame:
    """A dot of 8 px: a level's value, or ``none`` in secondary text."""
    shown = QFrame()
    shown.setFixedSize(8, 8)
    shown.setProperty("dot", kind)
    return shown


def mark(shown: QFrame, kind: str) -> None:
    """Give a dot another kind, and draw it so."""
    shown.setProperty("dot", kind)
    style = shown.style()
    style.unpolish(shown)
    style.polish(shown)


def badge(text: str, kind: str) -> QLabel:
    """A pill: a level's value, ``advisory`` or ``danger``."""
    label = QLabel(text)
    label.setProperty("badge", kind)
    label.setFixedHeight(BADGE_HEIGHT)
    return label


class _IconButton(QPushButton):
    """A button whose icon is drawn again in the palette's colours when they change."""

    def __init__(self, look: Look, text: str, icon: str, colour: Callable[[Palette], str]) -> None:
        super().__init__(text)
        self._look, self._icon, self._colour = look, icon, colour
        look.changed.connect(self._draw)
        self._draw(look.palette)

    def _draw(self, palette: Palette) -> None:
        shown = QIcon()
        ratio = self.devicePixelRatioF()
        for mode, colour in (
            (QIcon.Mode.Normal, self._colour(palette)),
            (QIcon.Mode.Disabled, palette.secondary),
        ):
            shown.addPixmap(icons.pixmap(self._icon, colour, 16, ratio), mode)
        self.setIcon(shown)
        self.setIconSize(QSize(16, 16))


def _text(palette: Palette) -> str:
    return palette.text


def _primary(palette: Palette) -> str:
    return palette.primary_text


def button(look: Look, text: str, *, role: str = "", icon: str | None = None) -> QPushButton:
    """A button: bordered on the canvas, or ``primary``, or ``danger``; with an icon in its
    text's colour, if given."""
    colour = _primary if role in {"primary", "danger"} else _text
    made = QPushButton(text) if icon is None else _IconButton(look, text, icon, colour)
    if role:
        made.setProperty("role", role)
    return made


def chip(look: Look, text: str, *, icon: str | None = None, checkable: bool = False) -> QPushButton:
    """A chip: bordered, on the accent's tint when it is on."""
    made = button(look, text, icon=icon)
    made.setProperty("role", "chip")
    made.setCheckable(checkable)
    return made


def link(text: str) -> QPushButton:
    """Accent text without a border, that acts as a button."""
    made = QPushButton(text)
    made.setProperty("role", "link")
    made.setCursor(Qt.CursorShape.PointingHandCursor)
    made.setFlat(True)
    return made


class Field(QLineEdit):
    """A field named ``name``, its placeholder unless it is given one, its icon at its left
    (``mark``) in secondary text; the icon's button is named as the field is."""

    def __init__(self, look: Look, name: str, icon: str, *, placeholder: str = "") -> None:
        super().__init__()
        self._icon = icon
        self.setPlaceholderText(placeholder or name)
        self.setAccessibleName(name)
        self.mark = self.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition)
        self.mark.setText(name)
        look.changed.connect(self._draw)
        self._draw(look.palette)

    def _draw(self, palette: Palette) -> None:
        drawn = icons.pixmap(self._icon, palette.secondary, 16, self.devicePixelRatioF())
        self.mark.setIcon(QIcon(drawn))


class Choice(QComboBox):
    """A field to choose one of a few values, the chevron drawn in secondary text."""

    def __init__(self, look: Look) -> None:
        super().__init__()
        self._look = look

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        colour = self._look.palette.secondary
        drawn = icons.pixmap("chevron-down", colour, 16, self.devicePixelRatioF())
        painter.drawPixmap(QPoint(self.width() - 24, (self.height() - 16) // 2), drawn)
        painter.end()


class Switch(QAbstractButton):
    """A switch, named ``name``: on, its track on the accent and its knob at the right; off,
    on the border colour with its knob at the left; disabled, at half strength; focused, in a
    ring of the accent. A click, or Space, asks to turn it (``clicked``): it turns only when it
    is set, once what it stands for has turned."""

    def __init__(self, look: Look, name: str) -> None:
        super().__init__()
        self._look = look
        self.setCheckable(True)
        self.setAccessibleName(name)
        self.setFixedSize(SWITCH_SIZE)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        look.changed.connect(self.update)

    def nextCheckState(self) -> None:
        """A click does not turn it."""

    def colours(self) -> tuple[str, str]:
        """Its track's colour and its knob's, in the palette in use."""
        palette = self._look.palette
        if self.isChecked():
            return palette.accent, palette.primary_text
        return palette.border, palette.canvas

    def paintEvent(self, event: QPaintEvent) -> None:
        track_colour, knob_colour = self.colours()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.5)
        track = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        radius = track.height() / 2
        if self.hasFocus():
            painter.setPen(QPen(QColor(self._look.palette.accent), 1))
            ring = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.drawRoundedRect(ring, radius + 2, radius + 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(track_colour))
        painter.drawRoundedRect(track, radius, radius)
        side = track.height() - 4
        left = track.right() - 2 - side if self.isChecked() else track.left() + 2
        painter.setBrush(QColor(knob_colour))
        painter.drawEllipse(QRectF(left, track.top() + 2, side, side))
        painter.end()


class Icon(QWidget):
    """An icon in one of the palette's colours, on a tile (radius 8) if given one."""

    def __init__(
        self,
        look: Look,
        name: str,
        colour: Callable[[Palette], str],
        *,
        size: int = 16,
        tile: Callable[[Palette], str] | None = None,
        side: int | None = None,
    ) -> None:
        super().__init__()
        self._look, self._name, self._colour, self._size, self._tile = (
            look,
            name,
            colour,
            size,
            tile,
        )
        self.setFixedSize(QSize(side or size, side or size))
        look.changed.connect(self.update)

    @property
    def name(self) -> str:
        return self._name

    def colours(self) -> tuple[str, str | None]:
        """The icon's colour and its tile's, in the palette in use."""
        palette = self._look.palette
        return self._colour(palette), None if self._tile is None else self._tile(palette)

    def paintEvent(self, event: QPaintEvent) -> None:
        colour, tile = self.colours()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if tile is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tile))
            painter.drawRoundedRect(self.rect(), 8, 8)
        drawn = icons.pixmap(self._name, colour, self._size, self.devicePixelRatioF())
        offset = (self.width() - self._size) // 2
        painter.drawPixmap(QPoint(offset, (self.height() - self._size) // 2), drawn)
        painter.end()


# --- check boxes -------------------------------------------------------------------------------


def check_colours(state: Qt.CheckState, palette: Palette) -> tuple[str, str, str | None]:
    """A check box's fill, border and mark: on the accent, with the mark in the primary button's
    text, when checked or partly; on the canvas with a border of secondary text otherwise."""
    if state == Qt.CheckState.Unchecked:
        return palette.canvas, palette.secondary, None
    return palette.accent, palette.accent, palette.primary_text


def paint_check(painter: QPainter, box: QRect, state: Qt.CheckState, palette: Palette) -> None:
    fill, border, mark = check_colours(state, palette)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(border), 1))
    painter.setBrush(QColor(fill))
    painter.drawRoundedRect(box.adjusted(0, 0, -1, -1), 4, 4)
    if mark is not None:
        name = "check" if state == Qt.CheckState.Checked else "minus"
        ratio = painter.device().devicePixelRatioF()
        drawn = icons.pixmap(name, mark, box.width() - 4, ratio)
        painter.drawPixmap(box.topLeft() + QPoint(2, 2), drawn)
    painter.restore()


class CheckBox(QCheckBox):
    """A check box drawn as the lists draw theirs, its text after it."""

    def __init__(self, look: Look, text: str) -> None:
        super().__init__(text)
        self._look = look

    def box(self) -> QRect:
        """Where the box is drawn: 2 px in, for the focus ring around it."""
        return QRect(2, (self.height() - CHECK) // 2, CHECK, CHECK)

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self.font())
        width = 2 + CHECK + 8 + metrics.horizontalAdvance(self.text())
        return QSize(width, max(ROW_HEIGHT - 8, metrics.height()))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event: QPaintEvent) -> None:
        palette = self._look.palette
        painter = QPainter(self)
        box = self.box()
        paint_check(painter, box, self.checkState(), palette)
        painter.setPen(QColor(palette.text if self.isEnabled() else palette.secondary))
        words = self.rect().adjusted(box.right() + 1 + 8, 0, 0, 0)
        painter.drawText(
            words, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text()
        )
        if self.hasFocus():
            painter.setPen(QPen(QColor(palette.accent), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box.adjusted(-2, -2, 1, 1), 5, 5)
        painter.end()


# --- lists -------------------------------------------------------------------------------------


def _advance(font: QFont, text: str) -> int:
    """How wide ``text`` is in ``font``, in whole pixels rounded up: given that, it is not cut."""
    return math.ceil(QFontMetricsF(font).horizontalAdvance(text))


def _small(font: QFont, *, bold: bool = False) -> QFont:
    small = QFont(font)
    small.setPixelSize(_SMALL)
    if bold:
        small.setWeight(QFont.Weight.DemiBold)
    return small


def cell_colours(
    palette: Palette, *, selected: bool = False, quiet: bool = False, enabled: bool = True
) -> tuple[str | None, str]:
    """A cell's background (none unless selected: the accent's tint) and its text's colour
    (secondary when quiet or disabled)."""
    background = palette.selection if selected else None
    return background, palette.secondary if quiet or not enabled else palette.text


def badge_colours(kind: str, palette: Palette) -> Badge:
    """A badge's colours: ``danger``'s, ``advisory``'s (the text on surface 2) or a level's."""
    if kind == "danger":
        return palette.danger_badge
    if kind == "advisory":
        return Badge(palette.text, palette.surface2)
    return palette.badges[Level(kind)]


_Index = QModelIndex | QPersistentModelIndex


class RowDelegate(QStyledItemDelegate):
    """How the window's lists draw a cell: see the module's docstring."""

    def __init__(self, look: Look, parent: QAbstractItemView) -> None:
        super().__init__(parent)
        self._look = look

    def _font(self, option: QStyleOptionViewItem, index: _Index) -> QFont:
        font = QFont(option.font)
        if index.data(EMPHASIS):
            font.setWeight(QFont.Weight.DemiBold)
        return font

    def sizeHint(self, option: QStyleOptionViewItem, index: _Index) -> QSize:
        font = self._font(option, index)
        metrics = QFontMetrics(font)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        kind = index.data(BADGE)
        if kind:
            small = QFontMetrics(_small(font, bold=True))
            return QSize(2 * _PAD + small.horizontalAdvance(text) + 16, ROW_HEIGHT)
        width = _advance(font, text)
        height = metrics.height()
        second = index.data(SECONDARY)
        if second:
            smaller = _small(font)
            width = max(width, _advance(smaller, str(second)))
            height += _LINE_GAP + QFontMetrics(smaller).height()
        if index.data(Qt.ItemDataRole.CheckStateRole) is not None:
            width += CHECK + _PAD
        if index.data(INITIAL):
            width += TILE + _PAD
            height = max(height, TILE)
        return QSize(width + 2 * _PAD, max(ROW_HEIGHT, height + 2 * _PAD))

    def check_box(self, option: QStyleOptionViewItem, index: _Index) -> QRect | None:
        """Where the cell's check box is drawn, if it has one."""
        if index.data(Qt.ItemDataRole.CheckStateRole) is None:
            return None
        rect = option.rect
        return QRect(rect.left() + _PAD, rect.center().y() - CHECK // 2 + 1, CHECK, CHECK)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: _Index) -> None:
        palette = self._look.palette
        rect = QRect(option.rect)
        painter.save()
        background, _ = cell_colours(
            palette, selected=bool(option.state & QStyle.StateFlag.State_Selected)
        )
        if background is not None:
            painter.fillRect(rect, QColor(background))
        painter.setPen(QPen(QColor(palette.border), 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        left = rect.left() + _PAD
        box = self.check_box(option, index)
        if box is not None:
            state = Qt.CheckState(index.data(Qt.ItemDataRole.CheckStateRole))
            paint_check(painter, box, state, palette)
            left = box.right() + 1 + _PAD
        initial = index.data(INITIAL)
        if initial:
            tile = QRect(left, rect.center().y() - TILE // 2 + 1, TILE, TILE)
            self._paint_tile(painter, tile, str(initial), option)
            left = tile.right() + 1 + _PAD
        space = QRect(left, rect.top(), rect.right() + 1 - _PAD - left, rect.height())
        kind = index.data(BADGE)
        if kind:
            self._paint_badge(
                painter, space, str(index.data(Qt.ItemDataRole.DisplayRole)), str(kind), option
            )
        else:
            self._paint_text(painter, space, option, index)
        painter.restore()

    def _paint_tile(
        self, painter: QPainter, tile: QRect, initial: str, option: QStyleOptionViewItem
    ) -> None:
        """The cell's tile on surface 2 (radius 8), its initial in semibold on it."""
        palette = self._look.palette
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.surface2))
        painter.drawRoundedRect(tile, 8, 8)
        font = QFont(option.font)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(palette.text))
        painter.drawText(tile, int(Qt.AlignmentFlag.AlignCenter), initial)

    def _paint_badge(
        self, painter: QPainter, space: QRect, text: str, kind: str, option: QStyleOptionViewItem
    ) -> None:
        colours = badge_colours(kind, self._look.palette)
        font = _small(option.font, bold=True)
        width = QFontMetrics(font).horizontalAdvance(text) + 16
        pill = QRect(space.left(), space.center().y() - BADGE_HEIGHT // 2 + 1, width, BADGE_HEIGHT)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colours.background))
        painter.drawRoundedRect(pill, BADGE_HEIGHT / 2, BADGE_HEIGHT / 2)
        painter.setFont(font)
        painter.setPen(QColor(colours.text))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), text)

    def _paint_text(
        self, painter: QPainter, space: QRect, option: QStyleOptionViewItem, index: _Index
    ) -> None:
        _, colour = cell_colours(
            self._look.palette,
            quiet=bool(index.data(QUIET)),
            enabled=bool(option.state & QStyle.StateFlag.State_Enabled),
        )
        font = self._font(option, index)
        metrics = QFontMetrics(font)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        second = index.data(SECONDARY)
        aligned = index.data(Qt.ItemDataRole.TextAlignmentRole)
        across = Qt.AlignmentFlag(aligned) if aligned is not None else Qt.AlignmentFlag.AlignLeft
        across &= Qt.AlignmentFlag.AlignHorizontal_Mask
        small = _small(font)
        height = metrics.height() + (_LINE_GAP + QFontMetrics(small).height() if second else 0)
        top = space.top() + (space.height() - height) // 2
        line = QRect(space.left(), top, space.width(), metrics.height())
        painter.setFont(font)
        painter.setPen(QColor(colour))
        elided = metrics.elidedText(text, option.textElideMode, space.width())
        painter.drawText(line, int(across | Qt.AlignmentFlag.AlignVCenter), elided)
        if second:
            small_metrics = QFontMetrics(small)
            under = QRect(
                space.left(), line.bottom() + 1 + _LINE_GAP, space.width(), small_metrics.height()
            )
            painter.setFont(small)
            painter.setPen(QColor(self._look.palette.secondary))
            shown = small_metrics.elidedText(str(second), option.textElideMode, space.width())
            painter.drawText(under, int(across | Qt.AlignmentFlag.AlignVCenter), shown)

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: _Index,
    ) -> bool:
        """A click on a check box turns it, as Qt's own delegate does; keys are Qt's."""
        if not isinstance(event, QMouseEvent):
            return super().editorEvent(event, model, option, index)
        box = self.check_box(option, index)
        flags = index.flags()
        can_check = bool(
            flags & Qt.ItemFlag.ItemIsUserCheckable and flags & Qt.ItemFlag.ItemIsEnabled
        )
        if box is None or not can_check or not box.contains(event.position().toPoint()):
            return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            state = Qt.CheckState(index.data(Qt.ItemDataRole.CheckStateRole))
            turned = (
                Qt.CheckState.Unchecked if state == Qt.CheckState.Checked else Qt.CheckState.Checked
            )
            model.setData(index, turned.value, Qt.ItemDataRole.CheckStateRole)
        return True


def rows(view: QAbstractItemView, look: Look) -> QAbstractItemView:
    """``view`` drawn as the window's lists: by ``RowDelegate``, without a frame, a grid or
    alternate rows, its header (if any) in capitals of small secondary text."""
    view.setItemDelegate(RowDelegate(look, view))
    view.setAlternatingRowColors(False)
    view.setFrameShape(QFrame.Shape.NoFrame)
    if isinstance(view, QTreeView):
        view.setUniformRowHeights(False)
        header = view.header()
        font = QFont(header.font())
        font.setCapitalization(QFont.Capitalization.AllUppercase)
        header.setFont(font)
    return view
