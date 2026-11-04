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


def _side(value: int, ground: int) -> int:
    return (value > ground) - (value < ground)


def drawn_in(image: QImage, colour: str, background: str, *, within: int = 2) -> bool:
    """What ``image`` draws on ``background`` is ``colour``: the pixel that differs most from the
    background is ``colour``, within the rounding of its edges (``within``, more for small text,
    whose thin strokes never reach their full colour).

    A channel at a time, among the pixels on its side of the background in every channel, for
    text drawn with subpixel antialiasing, as Ubuntu draws it: a stroke there reaches its colour
    in red at one pixel and in blue at another, and the pixel that differs most has neither.
    What else the image has, on the other side, as a tile's corners, is left out."""
    plain = image.convertToFormat(QImage.Format.Format_RGB32)
    ground = QColor(background)
    pixels = [plain.pixelColor(x, y) for x in range(plain.width()) for y in range(plain.height())]
    strongest = max(pixels, key=lambda pixel: _distance(pixel, ground))
    channels = (QColor.red, QColor.green, QColor.blue)
    sides = [_side(channel(strongest), channel(ground)) for channel in channels]
    alike = [
        pixel
        for pixel in pixels
        if all(
            _side(channel(pixel), channel(ground)) in (side, 0)
            for channel, side in zip(channels, sides, strict=True)
        )
    ]
    reached = QColor(
        *(
            channel(ground) + side * max(abs(channel(pixel) - channel(ground)) for pixel in alike)
            for channel, side in zip(channels, sides, strict=True)
        )
    )
    return _distance(reached, QColor(colour)) <= within
