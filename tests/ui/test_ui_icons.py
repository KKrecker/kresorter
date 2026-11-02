"""The icons: Lucide's, shipped in ``safeclean/ui/icons`` with their licence, drawn in one
colour of the palette (decision 0014, item 47)."""

from importlib.resources import files

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from safeclean.ui import icons
from safeclean.ui.theme import DARK, LIGHT
from support.drawn import ink, inked_in

_SHIPPED = files("safeclean.ui").joinpath("icons")


def test_every_icon_is_shipped_and_every_shipped_icon_is_named() -> None:
    # [0014.47]
    shipped = sorted(
        entry.name.removesuffix(".svg")
        for entry in _SHIPPED.iterdir()
        if entry.name.endswith(".svg")
    )
    assert shipped == sorted(icons.NAMES)
    assert list(icons.NAMES) == sorted(icons.NAMES)


def test_the_icons_licence_is_shipped_with_them() -> None:
    # [0014.47]
    licence = _SHIPPED.joinpath("LICENSE").read_text(encoding="utf-8")
    assert licence.startswith("ISC License")
    assert "Lucide Contributors" in licence


@pytest.mark.parametrize("name", icons.NAMES)
def test_an_icon_is_lucide_s_drawn_in_the_colour_asked(name: str) -> None:
    # [0014.47]
    shipped = icons.svg(name)
    assert "lucide" in shipped
    assert 'stroke="currentColor"' in shipped
    for colour in (LIGHT.secondary, DARK.accent):
        drawn = icons.image(name, colour, 18)
        assert (drawn.width(), drawn.height()) == (18, 18)
        assert inked_in(drawn, colour)


def test_an_icon_is_drawn_at_the_screen_s_pixel_ratio() -> None:
    # [0014.47]
    sharp = icons.image("search", LIGHT.text, 16, 2.0)
    assert (sharp.width(), sharp.height()) == (32, 32)
    assert sharp.devicePixelRatio() == 2.0
    assert inked_in(sharp, LIGHT.text)
    assert len(ink(sharp)) > len(ink(icons.image("search", LIGHT.text, 16)))


def test_an_icon_as_a_pixmap(qapp: QApplication) -> None:
    # [0014.47]
    drawn = icons.pixmap("folder", DARK.text, 20, 1.5)
    assert isinstance(drawn, QPixmap)
    assert (drawn.width(), drawn.height()) == (30, 30)
    assert drawn.devicePixelRatio() == 1.5
    assert inked_in(drawn.toImage(), DARK.text)
