"""What the window's tests share: an environment made for tmp_path, a window, the dialogs a test
answers, and the buttons that have neither a text nor an accessible name (decision 0014, items
18, 38 and 39)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtWidgets import QAbstractButton, QWidget
from pytestqt.qtbot import QtBot

from safeclean.core.heuristics import Platform
from safeclean.core.open_files import OpenFileChecker
from safeclean.environment import Environment
from safeclean.ui.dialogs import Confirmation, Dialogs
from safeclean.ui.i18n import Language, Translator
from safeclean.ui.window import Window
from support.cli import autostart_context, scan_context
from support.files import aged, write


def environment(
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    *,
    platform: Platform = "linux",
    open_files: OpenFileChecker | None = None,
) -> Environment:
    """The window's environment for tmp_path: ``zone`` the one scan zone, ``data_dir`` the data
    directory, autostart under tmp_path, no setting of the local AI."""
    return Environment(
        scan_context=lambda: scan_context(tmp_path, zone, data_dir, open_files, platform=platform),
        autostart_context=lambda: autostart_context(platform, tmp_path),
        llm_env={},
    )


def junk_tree(zone: Path) -> dict[str, Path]:
    """Four Safe files (``kept`` the kept copy of a duplicate pair, ``copy`` the other), a
    Likely safe copy (``backup``, of ``photo``, which is no finding), a Review file and a file
    that is no finding."""
    return {
        "m": write(zone / "proj" / "__pycache__" / "m.cpython-313.pyc", b"bytecode"),
        "n": write(zone / "lib" / "__pycache__" / "n.cpython-313.pyc", b"other bytecode!"),
        "kept": aged(write(zone / "a" / "__pycache__" / "x.pyc", b"same"), 9),
        "copy": aged(write(zone / "b" / "__pycache__" / "x.pyc", b"same"), 3),
        "photo": aged(write(zone / "photos" / "img.jpg", b"jpeg-bytes"), 10),
        "backup": aged(write(zone / "backup" / "img.jpg", b"jpeg-bytes"), 5),
        "old": aged(write(zone / "old" / "report.pdf", b"old report"), 800),
        "notes": write(zone / "notes.txt", b"hello"),
    }


class FakeDialogs:
    """The dialogs a page would block on, answered as the test says; every question is kept.
    ``meanwhile`` runs while the next confirmation is open: another program at work."""

    def __init__(self, *, confirm: bool = True, folders: Sequence[Path | None] = ()) -> None:
        self.answer = confirm
        self.folders = list(folders)
        self.asked: list[Confirmation] = []
        self.meanwhile: list[Callable[[], object]] = []

    def confirm(self, confirmation: Confirmation) -> bool:
        self.asked.append(confirmation)
        for change in self.meanwhile:
            change()
        self.meanwhile.clear()
        return self.answer

    def choose_folder(self) -> Path | None:
        return self.folders.pop(0)

    @property
    def dialogs(self) -> Dialogs:
        return Dialogs(confirm=self.confirm, choose_folder=self.choose_folder)


def make_window(
    qtbot: QtBot,
    environment: Environment,
    *,
    language: Language = "en",
    dialogs: FakeDialogs | None = None,
) -> Window:
    """A window shown offscreen, closed and deleted after the test."""
    window = Window(environment, Translator(language), (dialogs or FakeDialogs()).dialogs)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


def wait_idle(qtbot: QtBot, window: Window) -> None:
    qtbot.waitUntil(lambda: window.tasks.running is None, timeout=10_000)


def scanned(qtbot: QtBot, window: Window) -> None:
    """Scan from the Overview page and wait until the findings are shown."""
    window.overview.scan_button.click()
    wait_idle(qtbot, window)


def unnamed(widget: QWidget) -> list[QAbstractButton]:
    """The buttons under ``widget`` with neither a text nor an accessible name."""
    return [
        button
        for button in widget.findChildren(QAbstractButton)
        if not (button.text().strip() or button.accessibleName().strip())
    ]
