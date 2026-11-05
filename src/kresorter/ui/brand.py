"""The application's mark and icon (decision 0019, items 3 and 4): the sidebar's mark, a tile of
the accent with its corners rounded and the shield in the middle in the primary button's text,
drawn at any side, in the light scheme's colours; the application's icon is the mark at each
side Windows shows, and ``Kresorter.exe``'s ICO is drawn from it too."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap

from kresorter.ui import icons
from kresorter.ui.theme import LIGHT

__all__ = ["GLYPH", "RADIUS", "SHIELD", "SIDES", "TILE", "app_icon", "mark"]

# The sidebar's mark (kresorter.ui.sidebar): a 28 px tile with corners of 8 px, a 16 px shield.
TILE, RADIUS, GLYPH, SHIELD = 28, 8, 16, "shield-check"
SIDES = (16, 20, 24, 32, 40, 48, 64, 256)  # those Windows shows, at each scale


def mark(side: int) -> QImage:
    """The sidebar's mark, ``side`` px square, as the sidebar draws it at 28 px."""
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    scale = side / TILE
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(LIGHT.accent))
    painter.drawRoundedRect(QRectF(0, 0, TILE, TILE), RADIUS, RADIUS)
    offset = (TILE - GLYPH) / 2
    glyph = icons.image(SHIELD, LIGHT.primary_text, GLYPH, scale)
    painter.drawImage(QRectF(offset, offset, GLYPH, GLYPH), glyph)
    painter.end()
    return image


def app_icon() -> QIcon:
    """The application's icon: the mark at each of ``SIDES``."""
    icon = QIcon()
    for side in SIDES:
        icon.addPixmap(QPixmap.fromImage(mark(side)))
    return icon
