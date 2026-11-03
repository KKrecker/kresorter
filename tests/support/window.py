"""What the window's tests share: an environment made for tmp_path, a window, the dialogs a test
answers, and the buttons that have neither a text nor an accessible name (decision 0014, items
18, 38 and 39)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from PySide6.QtWidgets import QAbstractButton, QTreeWidgetItem, QWidget
from pytestqt.qtbot import QtBot

from kresorter.autostart.registry import UserRegistry
from kresorter.core.heuristics import Platform
from kresorter.core.open_files import OpenFileChecker
from kresorter.environment import Environment
from kresorter.llm.transport import LIMITS, Limits
from kresorter.ui.dialogs import Confirmation, Dialogs
from kresorter.ui.i18n import Language, Translator
from kresorter.ui.window import Window
from support.cli import autostart_context, scan_context
from support.files import aged, write


def environment(
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    *,
    platform: Platform = "linux",
    open_files: OpenFileChecker | None = None,
    registry: UserRegistry | None = None,
    llm_env: Mapping[str, str] | None = None,
    llm_limits: Limits = LIMITS,
) -> Environment:
    """The window's environment for tmp_path: ``zone`` the one scan zone, ``data_dir`` the data
    directory, autostart under tmp_path (``registry`` on Windows), the local AI's settings
    ``llm_env`` (none by default)."""
    return Environment(
        scan_context=lambda: scan_context(tmp_path, zone, data_dir, open_files, platform=platform),
        autostart_context=lambda: autostart_context(platform, tmp_path, registry),
        llm_env={} if llm_env is None else llm_env,
        llm_limits=llm_limits,
    )


def settled(data_dir: Path, **values: object) -> Path:
    """``settings.json`` in the data directory, as the window writes it, with ``values``."""
    data_dir.mkdir(parents=True, exist_ok=True)
    data_dir.chmod(0o700)
    path = data_dir / "settings.json"
    path.write_text(json.dumps({"language": "system", "include_machine": False, **values}))
    return path


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
    """A window shown offscreen, closed and deleted after the test, once it has looked for
    unfinished work."""
    window = Window(environment, Translator(language), (dialogs or FakeDialogs()).dialogs)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    wait_idle(qtbot, window)
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


def children(item: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    """The rows under ``item``, in order; under a tree's invisible root, its top-level rows."""
    rows = []
    for index in range(item.childCount()):
        row = item.child(index)
        assert row is not None
        rows.append(row)
    return rows
