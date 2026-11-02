"""What the window draws, read from its pixels: the colour of an icon's ink (decision 0014,
item 47)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QImage


def ink(image: QImage) -> list[QColor]:
    """The colours of ``image``'s pixels that are at least half opaque."""
    plain = image.convertToFormat(QImage.Format.Format_ARGB32)
    return [
        colour
        for x in range(plain.width())
        for y in range(plain.height())
        if (colour := plain.pixelColor(x, y)).alpha() >= 128
    ]


def inked_in(image: QImage, colour: str) -> bool:
    """``image`` has ink, all of it ``colour`` (within the rounding of its edges)."""
    wanted = QColor(colour)
    found = ink(image)
    return bool(found) and all(_distance(one, wanted) <= 2 for one in found)


def _distance(one: QColor, other: QColor) -> int:
    return max(
        abs(one.red() - other.red()),
        abs(one.green() - other.green()),
        abs(one.blue() - other.blue()),
    )


def drawn_in(image: QImage, colour: str, background: str, *, within: int = 2) -> bool:
    """What ``image`` draws on ``background`` is ``colour``: the pixel that differs most from the
    background is ``colour``, within the rounding of its edges (``within``, more for small text,
    whose thin strokes never reach their full colour)."""
    plain = image.convertToFormat(QImage.Format.Format_RGB32)
    ground = QColor(background)
    pixels = [plain.pixelColor(x, y) for x in range(plain.width()) for y in range(plain.height())]
    strongest = max(pixels, key=lambda pixel: _distance(pixel, ground))
    return _distance(strongest, QColor(colour)) <= within
