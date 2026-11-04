"""The window's motion (decision 0018, items 6-10): a page fades in, a switch's knob slides,
what can be clicked shows the pointer over it, and a scan shows that it works; with
``motion.DURATION_MS`` at 0 nothing moves. The window's other tests draw the end at once; these
alone keep the motion of the window as it ships."""

import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget
from pytestqt.qtbot import QtBot

from kresorter.analysis.report import AnalysisReport
from kresorter.analysis.run import analyze_paths
from kresorter.analysis.size_age import Thresholds
from kresorter.core.scanner import Progress, ScanContext, ScanReport
from kresorter.ui import motion, overview
from kresorter.ui.parts import Switch
from kresorter.ui.theme import LIGHT, Look
from kresorter.ui.window import Window
from support.window import FakeDialogs, environment, make_window, wait_idle

LEFT = Qt.MouseButton.LeftButton


@pytest.fixture
def still(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(motion, "DURATION_MS", 0)


def _window(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs | None = None
) -> Window:
    """The window on Overview, once its first page faded in."""
    made = make_window(qtbot, environment(tmp_path, zone, data_dir), dialogs=dialogs)
    qtbot.waitUntil(lambda: made.overview.graphicsEffect() is None, timeout=5000)
    return made


def _switch(qtbot: QtBot) -> Switch:
    """A switch, off, shown."""
    holder = QWidget()
    qtbot.addWidget(holder)
    made = Switch(Look(holder), "Sync")
    made.setParent(holder)
    holder.show()
    qtbot.waitExposed(holder)
    return made


def _colour(widget: QWidget, x: int, y: int) -> str:
    return widget.grab().toImage().pixelColor(x, y).name().upper()


def _hover(qtbot: QtBot, widget: QWidget) -> None:
    """The pointer over ``widget``, near its left edge, once its page is laid out."""
    QApplication.processEvents()
    QTest.mouseMove(widget, QPoint(6, widget.height() // 2))
    qtbot.waitUntil(widget.underMouse)
    QApplication.processEvents()


def _slow_scan(monkeypatch: pytest.MonkeyPatch, outcome: str = "done") -> threading.Event:
    """The window's scan, held until the event is set; then done, or failed."""
    released = threading.Event()

    def slow(
        paths: list[str], context: ScanContext, thresholds: Thresholds, *, progress: Progress
    ) -> tuple[ScanReport, AnalysisReport]:
        progress(1500)
        released.wait(10)
        if outcome == "failed":
            raise OSError("the disk went away")
        return analyze_paths(paths, context, thresholds, progress=progress)

    monkeypatch.setattr(overview, "analyze_paths", slow)
    return released


# --- a page fades in [0018.6] --------------------------------------------------------------------


def test_the_motion_takes_150_ms() -> None:
    # [0018.6] [0018.7]
    assert motion.DURATION_MS == 150


def test_a_page_that_opens_fades_in_usable_at_once_and_the_effect_is_removed_when_it_ends(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.6] A click on the page while it fades does what it does.
    folder = tmp_path / "photos"
    folder.mkdir()
    window = _window(qtbot, tmp_path, zone, data_dir, FakeDialogs(folders=[folder]))
    page = window.overview
    window.show_page("findings")

    window.show_page("overview")

    effect = page.graphicsEffect()
    assert isinstance(effect, QGraphicsOpacityEffect)
    assert effect.opacity() < 1
    assert window.pages.currentWidget() is page
    assert window.findings.graphicsEffect() is None  # its fade ended when Overview opened
    QTest.mouseClick(page.add_button, LEFT)
    assert folder in page.roots()
    qtbot.waitUntil(lambda: page.graphicsEffect() is None, timeout=5000)


# --- a switch slides [0018.7] --------------------------------------------------------------------


def test_a_switch_that_turns_slides_its_knob_its_state_the_new_one_at_once(qtbot: QtBot) -> None:
    # [0018.7] Its track's colour too is the new state's at once: only the knob moves.
    switch = _switch(qtbot)
    assert switch.knob() == 0.0

    switch.setChecked(True)

    assert switch.isChecked()
    assert switch.colours() == (LIGHT.accent, LIGHT.primary_text)
    assert switch.knob() < 1.0
    qtbot.waitUntil(lambda: switch.knob() == 1.0, timeout=5000)

    switch.setChecked(False)

    assert not switch.isChecked()
    assert switch.knob() > 0.0
    qtbot.waitUntil(lambda: switch.knob() == 0.0, timeout=5000)


def test_a_switch_not_shown_is_drawn_at_its_side_at_once(qtbot: QtBot) -> None:
    # [0018.7] As a list of switches is filled: none of them slides when it is shown.
    holder = QWidget()
    qtbot.addWidget(holder)
    switch = Switch(Look(holder), "Sync")
    switch.setChecked(True)
    assert switch.knob() == 1.0


# --- hover [0018.8] ------------------------------------------------------------------------------


@pytest.mark.usefixtures("still")
def test_a_button_shows_the_pointer_over_it_on_surface_2_a_primary_one_on_the_accent(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.8]
    window = _window(qtbot, tmp_path, zone, data_dir)
    window.show_page("settings")
    check = window.settings.check_button
    assert _colour(check, 6, check.height() // 2) == LIGHT.canvas
    _hover(qtbot, check)
    assert _colour(check, 6, check.height() // 2) == LIGHT.surface2

    window.show_page("overview")
    scan = window.overview.scan_button
    assert _colour(scan, 6, scan.height() // 2) == LIGHT.accent_text
    _hover(qtbot, scan)
    assert _colour(scan, 6, scan.height() // 2) == LIGHT.accent


@pytest.mark.usefixtures("still")
def test_a_chip_and_a_card_that_opens_a_page_show_the_pointer_over_them_by_an_accent_border(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.8] A card with a link inside is no card that opens a page: its border stays.
    window = _window(qtbot, tmp_path, zone, data_dir)
    page = window.overview
    chip = page.chips()[0]
    card = page.services["quarantine"]
    middle = chip.height() // 2
    assert _colour(chip, 0, middle) == LIGHT.border
    assert _colour(card, 0, card.height() // 2) == LIGHT.border
    _hover(qtbot, chip)
    assert _colour(chip, 0, middle) == LIGHT.accent
    _hover(qtbot, card)
    assert _colour(chip, 0, middle) == LIGHT.border
    assert _colour(card, 0, card.height() // 2) == LIGHT.accent


# --- a scan shows that it works [0018.9] ---------------------------------------------------------


def test_while_a_scan_runs_its_card_shows_a_moving_bar_and_the_status_line_the_files_read(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0018.9] [0018.16]
    released = _slow_scan(monkeypatch)
    window = _window(qtbot, tmp_path, zone, data_dir)
    bar = window.overview.scan_bar
    assert bar.isHidden()
    assert window.overview.scan_card.isAncestorOf(bar)

    window.overview.scan_button.click()

    assert bar.isVisible()
    assert bar.is_moving
    translator = window.translator
    read = translator.text("task.read", task="Scanning", read=translator.count("read", 1500))
    qtbot.waitUntil(lambda: window.status.text() == read, timeout=5000)
    first = bar.segment()
    qtbot.waitUntil(lambda: bar.segment() != first, timeout=5000)
    assert bar.segment().width() < bar.width()
    released.set()
    wait_idle(qtbot, window)
    assert bar.isHidden()
    assert not bar.is_moving
    assert window.overview.scanned is not None


def test_a_scan_that_fails_stops_its_bar(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0018.9]
    released = _slow_scan(monkeypatch, "failed")
    window = _window(qtbot, tmp_path, zone, data_dir)
    bar = window.overview.scan_bar
    window.overview.scan_button.click()
    assert bar.is_moving
    released.set()
    wait_idle(qtbot, window)
    assert window.message.text() == "Scanning failed: the disk went away"
    assert bar.isHidden()
    assert not bar.is_moving


# --- motion can be off [0018.10] -----------------------------------------------------------------


@pytest.mark.usefixtures("still")
def test_with_no_motion_a_page_opens_as_it_ends(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.10]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    assert window.overview.graphicsEffect() is None
    window.show_page("findings")
    assert window.findings.graphicsEffect() is None


@pytest.mark.usefixtures("still")
def test_with_no_motion_a_switch_is_at_its_side_at_once(qtbot: QtBot) -> None:
    # [0018.10]
    switch = _switch(qtbot)
    switch.setChecked(True)
    assert switch.knob() == 1.0
    switch.setChecked(False)
    assert switch.knob() == 0.0


@pytest.mark.usefixtures("still")
def test_with_no_motion_a_scan_s_bar_is_drawn_whole_and_still(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0018.10] [0018.9] The status line still counts the files read.
    released = _slow_scan(monkeypatch)
    window = _window(qtbot, tmp_path, zone, data_dir)
    bar = window.overview.scan_bar
    window.overview.scan_button.click()
    assert bar.isVisible()
    assert not bar.is_moving
    assert bar.segment() == QRectF(bar.rect())
    qtbot.waitUntil(lambda: "1500 files read" in window.status.text(), timeout=5000)
    assert bar.segment() == QRectF(bar.rect())
    released.set()
    wait_idle(qtbot, window)
    assert bar.isHidden()
