"""The application's mark and icon (decision 0019, item 3): ``ui.brand`` draws the sidebar's
mark, the shield on the accent's tile, at any side, and makes of it the application's icon,
which ``ui.app`` sets before the first window opens."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from kresorter.ui import app, brand
from kresorter.ui.dialogs import Confirmation, ConfirmDialog
from kresorter.ui.theme import LIGHT
from support.drawn import drawn_in
from support.window import environment, make_window


class Opened(Exception):
    """The first window would open here."""


@pytest.fixture
def no_icon(qapp: QApplication) -> Iterator[QApplication]:
    """The application without an icon, then with the one it had."""
    had = qapp.windowIcon()
    qapp.setWindowIcon(QIcon())
    yield qapp
    qapp.setWindowIcon(had)


def _pixels(image: QImage) -> list[int]:
    plain = image.convertToFormat(QImage.Format.Format_ARGB32)
    return [plain.pixel(x, y) for y in range(plain.height()) for x in range(plain.width())]


def _sides(icon: QIcon) -> list[int]:
    return sorted(size.width() for size in icon.availableSizes())


@pytest.mark.parametrize("side", [16, 28, 48, 100, 256])
def test_the_mark_is_the_shield_on_the_accents_tile_at_any_side(
    qapp: QApplication, side: int
) -> None:
    # [0019.3] the corners round, so transparent; the shield in the primary button's text
    drawn = brand.mark(side)

    assert (drawn.width(), drawn.height()) == (side, side)
    assert drawn.pixelColor(0, 0).alpha() == 0
    assert drawn.pixelColor(side // 2, 0).name() == LIGHT.accent.lower()
    assert drawn.pixelColor(side // 2, 0).alpha() == 255
    assert drawn_in(drawn, LIGHT.primary_text, LIGHT.accent)


def test_the_mark_is_the_sidebars(qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path) -> None:
    # [0019.3] where the mark is opaque, the sidebar shows it in the light scheme
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    assert window.look.palette is LIGHT
    sidebar = window.sidebar.mark
    assert (sidebar.name, sidebar.width(), sidebar.height()) == (
        brand.SHIELD,
        brand.TILE,
        brand.TILE,
    )
    shown = sidebar.grab().toImage()
    drawn = brand.mark(brand.TILE)

    for y in range(brand.TILE):
        for x in range(brand.TILE):
            if drawn.pixelColor(x, y).alpha() == 255:
                one, other = drawn.pixelColor(x, y), shown.pixelColor(x, y)
                assert abs(one.red() - other.red()) <= 8, (x, y)
                assert abs(one.green() - other.green()) <= 8, (x, y)
                assert abs(one.blue() - other.blue()) <= 8, (x, y)


def test_the_applications_icon_is_the_mark_at_each_side_windows_shows(qapp: QApplication) -> None:
    # [0019.3] 16 to 256 px
    icon = brand.app_icon()

    assert brand.SIDES == (16, 20, 24, 32, 40, 48, 64, 256)
    assert _sides(icon) == list(brand.SIDES)
    for side in brand.SIDES:
        shown = icon.pixmap(QSize(side, side)).toImage()
        assert (shown.width(), shown.height()) == (side, side)
        assert _pixels(shown) == _pixels(brand.mark(side)), side


def test_the_application_has_the_icon_before_the_first_window_opens(
    no_icon: QApplication,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0019.3] the title bar, the taskbar, Alt+Tab: every window's icon is the application's
    seen: list[list[int]] = []

    def opening(*_: object) -> None:
        seen.append(_sides(QApplication.windowIcon()))
        raise Opened

    monkeypatch.setattr(app, "_open", opening)
    with pytest.raises(Opened):
        app.run(["kresorter-ui"], environment(tmp_path, zone, data_dir))

    assert seen == [list(brand.SIDES)]


def test_the_self_test_window_has_the_icon_too(
    no_icon: QApplication,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0019.3]
    seen: list[list[int]] = []

    def testing(*_: object) -> int:
        seen.append(_sides(QApplication.windowIcon()))
        return 0

    monkeypatch.setattr(app, "self_test", testing)
    found = app.run(["kresorter-ui"], environment(tmp_path, zone, data_dir), tmp_path / "r.txt")

    assert (found, seen) == (0, [list(brand.SIDES)])


def test_every_window_and_dialog_shows_the_applications_icon(
    qtbot: QtBot, no_icon: QApplication, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.3] none sets an icon of its own, so each shows the application's
    no_icon.setWindowIcon(brand.app_icon())
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    dialog = ConfirmDialog(window, window.translator, Confirmation("?", "", (), "OK"))
    qtbot.addWidget(dialog)

    assert _sides(window.windowIcon()) == list(brand.SIDES)
    assert _sides(dialog.windowIcon()) == list(brand.SIDES)
