"""The sidebar (decision 0014, items 18 and 45).

232 px wide, on surface: the mark and ``safeclean``; the pages, each with its icon, and Settings
apart at the bottom; under it, the open-file check and the local AI, each with a dot. The pages
are two lists, one selection between them: the arrow keys cross from one to the other, Home and
End go to the first page and to Settings. The current page is on surface 2 with a radius of 8,
in semibold, without a focus rectangle; a page's number, when it has one, at the right.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from safeclean.ui import icons
from safeclean.ui.i18n import Translator
from safeclean.ui.parts import Icon, Note, divider, dot, hbox, mark, vbox
from safeclean.ui.theme import Look, Palette

__all__ = ["ICONS", "NAV_ROW", "WIDTH", "NavDelegate", "Sidebar", "nav_style"]

WIDTH = 232
NAV_ROW = 38
ICONS = {
    "overview": "house",
    "findings": "search",
    "organize": "folder",
    "autostart": "power",
    "quarantine": "archive",
    "settings": "sliders-horizontal",
}
_ICON = Qt.ItemDataRole.UserRole + 40
_COUNT = Qt.ItemDataRole.UserRole + 41
_Index = QModelIndex | QPersistentModelIndex


def nav_style(palette: Palette, *, current: bool) -> tuple[str | None, str, QFont.Weight]:
    """A page's background (none unless current), its icon's colour, its text's weight; the
    text is in the text colour."""
    if current:
        return palette.surface2, palette.text, QFont.Weight.DemiBold
    return None, palette.secondary, QFont.Weight.Normal


class NavDelegate(QStyledItemDelegate):
    def __init__(self, look: Look, parent: QAbstractItemView) -> None:
        super().__init__(parent)
        self._look = look

    def sizeHint(self, option: QStyleOptionViewItem, index: _Index) -> QSize:
        return QSize(0, NAV_ROW)  # as wide as the list

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: _Index) -> None:
        current = bool(option.state & QStyle.StateFlag.State_Selected)
        palette = self._look.palette
        background, icon, weight = nav_style(palette, current=current)
        rect = QRect(option.rect).adjusted(0, 1, 0, -1)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if background is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(rect, 8, 8)
        ratio = painter.device().devicePixelRatioF()
        drawn = icons.pixmap(str(index.data(_ICON)), icon, 18, ratio)
        painter.drawPixmap(QPoint(rect.left() + 10, rect.center().y() - 8), drawn)
        font = QFont(option.font)
        font.setWeight(weight)
        painter.setFont(font)
        painter.setPen(QColor(palette.text))
        words = rect.adjusted(40, 0, -12, 0)
        middle = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        painter.drawText(words, middle, str(index.data(Qt.ItemDataRole.DisplayRole)))
        number = index.data(_COUNT)
        if number is not None:
            small = QFont(option.font)
            small.setPixelSize(13)
            painter.setFont(small)
            painter.setPen(QColor(palette.secondary))
            right = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            painter.drawText(words, right, str(number))
        painter.restore()


class _Pages(QListWidget):
    """One list of pages; the keys that leave it are the sidebar's."""

    def __init__(self, sidebar: Sidebar, look: Look) -> None:
        super().__init__()
        self._sidebar = sidebar
        self.setProperty("role", "nav")
        self.setItemDelegate(NavDelegate(look, self))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        row = self._sidebar.crossing(self, Qt.Key(event.key()))
        if row is None:
            super().keyPressEvent(event)
            return
        self._sidebar.setCurrentRow(row)


class Sidebar(QFrame):
    """``pages`` in the list at the top, ``apart`` at the bottom; rows count from the top."""

    currentRowChanged = Signal(int)

    def __init__(
        self, translator: Translator, look: Look, pages: Sequence[str], apart: Sequence[str]
    ) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(WIDTH)
        self._names = [*pages, *apart]
        self._row = -1
        text = translator.text
        self.mark = Icon(look, "shield-check", _primary_text, size=16, tile=_accent, side=28)
        brand = QLabel(text("app.title"))
        brand.setObjectName("brand")
        self.lists = (_Pages(self, look), _Pages(self, look))
        self.lists[0].setAccessibleName(text("sidebar.pages"))
        self.lists[1].setAccessibleName(text("page.settings"))
        for names, listed in zip((pages, apart), self.lists, strict=True):
            for name in names:
                item = QListWidgetItem(text(f"page.{name}"))
                item.setData(_ICON, ICONS[name])
                listed.addItem(item)
            listed.setFixedHeight(len(names) * NAV_ROW)
            listed.currentRowChanged.connect(lambda row, listed=listed: self._changed(listed, row))
        self.open_files_dot, self.open_files = dot("none"), Note(self, role="secondary")
        self.ai_dot, self.ai = dot("none"), Note(self, role="secondary")

        mark = hbox(spacing=12, margins=(4, 0, 0, 0))
        mark.addWidget(self.mark)
        mark.addWidget(brand, 1)
        layout = vbox(self, margins=(12, 16, 12, 16), spacing=0)
        layout.addLayout(mark)
        layout.addSpacing(24)
        layout.addWidget(self.lists[0])
        layout.addStretch(1)
        layout.addWidget(self.lists[1])
        layout.addSpacing(12)
        layout.addWidget(divider())
        layout.addSpacing(12)
        for shown, line in ((self.open_files_dot, self.open_files), (self.ai_dot, self.ai)):
            beside = vbox(margins=(0, 4, 0, 0))  # the dot at the middle of the first line
            beside.addWidget(shown)
            beside.addStretch(1)
            status = hbox(spacing=8, margins=(8, 4, 0, 4))
            status.addLayout(beside)
            status.addWidget(line, 1)
            layout.addLayout(status)

    # --- the pages -----------------------------------------------------------------------------

    def count(self) -> int:
        return len(self._names)

    def _place(self, row: int) -> tuple[QListWidget, int]:
        top = self.lists[0].count()
        return (self.lists[0], row) if row < top else (self.lists[1], row - top)

    def item(self, row: int) -> QListWidgetItem:
        listed, local = self._place(row)
        found = listed.item(local)
        assert found is not None
        return found

    def text(self, row: int) -> str:
        return self.item(row).text()

    def currentRow(self) -> int:
        return self._row

    def setCurrentRow(self, row: int) -> None:
        listed, local = self._place(row)
        listed.setCurrentRow(local)
        if any(other.hasFocus() for other in self.lists):
            listed.setFocus()

    def current_list(self) -> QListWidget:
        """The list the current page is in."""
        return self._place(self._row)[0]

    def marked(self) -> list[int]:
        """The rows drawn as the current page."""
        return [row for row in range(self.count()) if self.item(row).isSelected()]

    def crossing(self, listed: QListWidget, key: Qt.Key) -> int | None:
        """The row a key goes to when it leaves ``listed`` or goes to an end; otherwise none."""
        top, bottom = self.lists
        if key == Qt.Key.Key_Home:
            return 0
        if key == Qt.Key.Key_End:
            return self.count() - 1
        if key == Qt.Key.Key_Down and listed is top and listed.currentRow() == top.count() - 1:
            return top.count()
        if key == Qt.Key.Key_Up and listed is bottom and listed.currentRow() == 0:
            return top.count() - 1
        return None

    def _changed(self, listed: QListWidget, local: int) -> None:
        if local < 0:
            return
        for other in self.lists:
            if other is not listed:
                other.setCurrentRow(-1)
                other.clearSelection()
        self._row = local if listed is self.lists[0] else self.lists[0].count() + local
        self.currentRowChanged.emit(self._row)

    def set_count(self, name: str, number: int | None) -> None:
        """The number shown at the right of the page ``name``; none for ``None``."""
        self.item(self._names.index(name)).setData(_COUNT, number)

    def count_of(self, name: str) -> int | None:
        found = self.item(self._names.index(name)).data(_COUNT)
        return None if found is None else int(found)

    # --- the status lines ----------------------------------------------------------------------

    def show_open_files(self, text: str, *, reliable: bool) -> None:
        self.open_files.setText(text)
        mark(self.open_files_dot, "safe" if reliable else "review")

    def show_ai(self, text: str, *, checked: bool | None) -> None:
        """``checked``: ``None`` until a Check ran, then whether every check passed."""
        self.ai.setText(text)
        mark(self.ai_dot, "none" if checked is None else "safe" if checked else "review")


def _primary_text(palette: Palette) -> str:
    return palette.primary_text


def _accent(palette: Palette) -> str:
    return palette.accent
