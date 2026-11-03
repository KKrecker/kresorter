"""The window's icons (decision 0014, item 47): Lucide's, shipped in ``kresorter/ui/icons`` with
their licence (ISC), read from the package and never written, and drawn in one colour of the
palette: an icon is drawn from its SVG with ``currentColor`` replaced by that colour, at the size
asked and the screen's pixel ratio."""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import QBuffer, QByteArray, QSize
from PySide6.QtGui import QImage, QImageReader, QPixmap

__all__ = ["NAMES", "image", "pixmap", "svg"]

NAMES = (
    "archive",
    "check",
    "chevron-down",
    "chevron-right",
    "download",
    "file-text",
    "folder",
    "house",
    "image",
    "lock",
    "minus",
    "music",
    "package",
    "plus",
    "power",
    "refresh-cw",
    "search",
    "shield-check",
    "sliders-horizontal",
    "sparkles",
    "square-play",
    "undo-2",
    "x",
)


def svg(name: str) -> str:
    """The SVG of the icon ``name``, as shipped."""
    return files("kresorter.ui").joinpath("icons", f"{name}.svg").read_text(encoding="utf-8")


def image(name: str, colour: str, size: int, ratio: float = 1.0) -> QImage:
    """The icon ``name`` in ``colour``, ``size`` px square at the pixel ratio ``ratio``."""
    data = QByteArray(svg(name).replace("currentColor", colour).encode("utf-8"))
    buffer = QBuffer(data)  # kept while the reader reads it, which opens it
    reader = QImageReader(buffer, QByteArray(b"svg"))
    side = round(size * ratio)
    reader.setScaledSize(QSize(side, side))
    drawn = reader.read()
    drawn.setDevicePixelRatio(ratio)
    return drawn


def pixmap(name: str, colour: str, size: int, ratio: float = 1.0) -> QPixmap:
    return QPixmap.fromImage(image(name, colour, size, ratio))
