"""The README's screenshots, made by a script, not drawn (decision 0015, items 26 and 27).

``PYTHONPATH=tests python -m support.screenshots [SCREEN...]``, from the repository with the
extra ``dev``, opens the window offscreen, 1280 x 800, in English, on a made-up tree in a
temporary home, and writes ``docs/screenshots/<screen>.png`` for each of the prototype's six
screens, every one when none is named. Nothing of the user's is read or written: home, the data
and settings folders are the temporary home's while it runs, the scan and autostart read only
there, and the local AI has no address. Every page is read first, as a user would have by then,
so that one screen looks the same whether it is made alone or with the others; the confirmation
is the real dialog, drawn over the window and then cancelled: nothing is moved.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn

from PySide6.QtCore import QCoreApplication, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from fakes import FakeOpenFiles, make_policy
from kresorter.analysis.score import Level
from kresorter.autostart.listing import AutostartContext
from kresorter.core.scanner import ScanContext
from kresorter.environment import Environment
from kresorter.llm.transport import LIMITS
from kresorter.organize.synced import NoSyncedFolders
from kresorter.ui.dialogs import Confirmation, ConfirmDialog, Dialogs
from kresorter.ui.i18n import Translator
from kresorter.ui.window import Window
from support.files import aged, write
from support.host import host_classifier, host_rules
from support.offscreen import system_fonts

__all__ = ["HEIGHT", "OUT", "SCREENS", "WIDTH", "main", "shoot"]

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "screenshots"
SCREENS = ("overview", "findings", "confirmation", "organize", "autostart", "findings-dark")
WIDTH, HEIGHT = 1280, 800
LIMIT_MS = 30_000  # what a page's task may take on the made-up tree
MIB = 1024 * 1024
PIP_CACHE = Path("pip", "http-v2", "a", "b", "c5e7.body")
HOME_VARIABLES = ("HOME", "USERPROFILE", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "LOCALAPPDATA")


# --- the made-up home ----------------------------------------------------------------------------


def sized(path: Path, size: int, days: int = 0) -> Path:
    """A file of ``size`` bytes that takes no room on the disk (a sparse one), ``days`` old."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as file:
        file.truncate(size)
    return aged(path, days) if days else path


def made_up_home(home: Path) -> None:
    """Caches, thumbnails, copies and old files in ``~/.cache`` and ``~/Downloads``, a project
    with its bytecode, and four programs that start at sign-in, one of them turned off. Every
    size is its own, so that only the copies meant as copies are."""
    cache = home / ".cache"
    sized(cache / "thumbnails" / "large" / "3f9c0a.png", 412_331)
    sized(cache / "thumbnails" / "normal" / "8e21d4.png", 96_412)
    sized(cache / PIP_CACHE, 18 * MIB + 3_301)
    sized(cache / "fontconfig" / "e13b20fd-le64.cache-9", 211_018)
    sized(cache / "mesa_shader_cache" / "index", 1 * MIB + 77)
    downloads = home / "Downloads"
    project = downloads / "site"
    sized(project / "__pycache__" / "app.cpython-313.pyc", 18_402)
    sized(project / "__pycache__" / "views.cpython-313.pyc", 27_119)
    sized(project / ".pytest_cache" / "v" / "cache" / "nodeids", 6_310)
    sized(project / "notes.tmp", 52_004)
    write(project / "app.py", b"print('site')\n")
    sized(downloads / "Thumbs.db", 1_327_104)
    photo = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 900
    aged(write(downloads / "IMG_2041.jpg", photo), 30)
    aged(write(downloads / "IMG_2041 (1).jpg", photo), 12)
    invoice = b"%PDF-1.7\n" + b"invoice " * 20_000
    aged(write(downloads / "invoice-october.pdf", invoice), 20)
    aged(write(downloads / "invoice-october (2).pdf", invoice), 19)
    sized(downloads / "ubuntu-24.04.1-desktop-amd64.iso", 6_114_656_256, 40)
    sized(downloads / "tax-return-2023.pdf", 1_204_811, 800)
    sized(downloads / "holiday.mp4", 734 * MIB + 5_120, 60)
    sized(downloads / "podcast-episode-12.mp3", 48 * MIB + 2_000, 5)
    sized(downloads / "photos-backup.zip", 211 * MIB + 9_001, 90)
    sized(downloads / "screenshot-2026-10-14.png", 288_120, 2)
    sized(downloads / "cv.docx", 61_440, 15)
    sized(downloads / "budget.xlsx", 23_808, 8)
    autostart = home / ".config" / "autostart"
    for name, title, command, on in (
        ("nextcloud", "Nextcloud", "/usr/bin/nextcloud --background", True),
        ("telegram", "Telegram Desktop", "/usr/bin/telegram-desktop -startintray", True),
        ("syncthing-start", "Start Syncthing", "/usr/bin/syncthing serve --no-browser", True),
        ("discord", "Discord", "/usr/bin/discord --start-minimized", False),
    ):
        lines = ["[Desktop Entry]", "Type=Application", f"Name={title}", f"Exec={command}"]
        if not on:
            lines.append("X-GNOME-Autostart-enabled=false")
        write(autostart / f"{name}.desktop", ("\n".join(lines) + "\n").encode())


def environment(home: Path) -> Environment:
    """The window's environment on the made-up home: the running system's rules but the one
    that marks the temporary folder as junk (the home is in it), ``~/.cache`` and
    ``~/Downloads`` the safe zones, autostart in ``~/.config/autostart``, no local AI."""
    data_dir = home / ".local" / "share" / "kresorter"
    rules = host_rules()
    roots = [home / ".cache", home / "Downloads"]
    checker = FakeOpenFiles()

    def scan_context() -> ScanContext:
        return ScanContext(
            policy=make_policy(home, default_roots=roots, app_data_dir=data_dir),
            open_files=checker,
            classifier=host_classifier(rules),
            open_files_checked=checker.reliable,
            platform="linux",
            synced=NoSyncedFolders(),
        )

    def autostart_context() -> AutostartContext:
        config = {"XDG_CONFIG_HOME": str(home / ".config"), "XDG_CONFIG_DIRS": str(home / "xdg")}
        return AutostartContext("linux", config, home=home, root=home, registry=_no_registry)

    return Environment(
        scan_context=scan_context,
        autostart_context=autostart_context,
        llm_env={},
        llm_limits=LIMITS,
    )


def _no_registry() -> NoReturn:  # never called: the made-up system is Linux
    raise AssertionError("no registry on Linux")


@contextmanager
def at_home(home: Path) -> Iterator[None]:
    """Home, the data and the settings folders the made-up home's, then the user's again."""
    places = {
        "HOME": home,
        "USERPROFILE": home,
        "XDG_DATA_HOME": home / ".local" / "share",
        "XDG_CONFIG_HOME": home / ".config",
        "LOCALAPPDATA": home / "AppData" / "Local",
    }
    before = {name: os.environ.get(name) for name in HOME_VARIABLES}
    os.environ.update({name: str(place) for name, place in places.items()})
    try:
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# --- the window, page by page --------------------------------------------------------------------


class Shots:
    """The window on the made-up home, and what each screen grabs."""

    def __init__(self, application: QCoreApplication, home: Path) -> None:
        self.application = application
        self.home = home
        self.confirmation: QPixmap | None = None
        translator = Translator("en")
        dialogs = Dialogs(confirm=self._confirm, choose_folder=lambda: home / "Downloads")
        self.window = Window(environment(home), translator, dialogs)
        self.window.resize(WIDTH, HEIGHT)
        self.window.show()
        self.settle()

    def settle(self) -> None:
        """Every event processed and no task running."""
        waited = 0
        while True:
            self.application.processEvents()
            if self.window.tasks.running is None:
                break
            if waited > LIMIT_MS:
                raise TimeoutError("a task of the window still runs")
            time.sleep(0.01)
            waited += 10
        self.application.processEvents()

    def page(self, name: str) -> None:
        self.window.show_page(name)
        self.settle()

    def read_every_page(self) -> None:
        """Autostart read, the Downloads folder planned, a scan, and on Findings the safe files
        chosen and the largest cache file shown in the detail, the list at its top."""
        self.page("autostart")
        self.page("organize")
        self.window.organize.choose_button.click()
        self.settle()
        self.page("overview")
        self.window.overview.scan_button.click()
        self.settle()
        findings = self.window.findings
        self.page("findings")
        findings.select_buttons[Level.SAFE].click()
        findings.tree.setCurrentItem(findings.item(self.home / ".cache" / PIP_CACHE))
        findings.tree.scrollToTop()
        self.settle()

    def grab(self, name: str) -> QPixmap:
        if name == "confirmation":
            return self._confirmed()
        if name == "findings-dark":
            return self._dark()
        self.page(name)
        return self.window.grab()

    def _dark(self) -> QPixmap:
        hints = QGuiApplication.styleHints()
        hints.colorSchemeChanged.emit(Qt.ColorScheme.Dark)
        try:
            self.page("findings")
            return self.window.grab()
        finally:
            hints.colorSchemeChanged.emit(hints.colorScheme())
            self.settle()

    def _confirmed(self) -> QPixmap:
        """Findings with the dialog Move to quarantine… asks, over it: cancelled."""
        self.page("findings")
        self.confirmation = None
        self.window.findings.move_button.click()
        self.settle()
        assert self.confirmation is not None, "Move to quarantine… asked nothing"
        return self.confirmation

    def _confirm(self, confirmation: Confirmation) -> bool:
        dialog = ConfirmDialog(self.window, self.window.translator, confirmation)
        dialog.show()
        self.application.processEvents()
        shot = self.window.grab()
        over = dialog.grab()
        dialog.reject()
        painter = QPainter(shot)
        painter.fillRect(shot.rect(), QColor(0, 0, 0, 64))
        place = QRect(QPoint(0, 0), over.size())
        place.moveCenter(shot.rect().center())
        painter.drawPixmap(place.topLeft(), over)
        painter.setPen(QColor(0, 0, 0, 48))
        painter.drawRect(place.adjusted(-1, -1, 0, 0))
        painter.end()
        self.confirmation = shot
        return False  # cancelled: nothing is moved

    def close(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()


def shoot(out: Path, screens: Sequence[str] = SCREENS) -> list[Path]:
    """``out/<screen>.png`` for each of ``screens``, on a made-up home that is gone after."""
    unknown = [screen for screen in screens if screen not in SCREENS]
    if unknown:
        raise ValueError(f"no screen {unknown[0]!r}: the screens are {', '.join(SCREENS)}")
    application = QApplication.instance() or QApplication(sys.argv[:1])
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="home-") as temporary:
        home = Path(temporary).resolve()
        made_up_home(home)
        with at_home(home):
            shots = Shots(application, home)
            try:
                shots.read_every_page()
                for screen in screens:
                    path = out / f"{screen}.png"
                    if not shots.grab(screen).save(str(path), "PNG"):
                        raise OSError(f"{path}: not written")
                    written.append(path)
            finally:
                shots.close()
    return written


def main(argv: Sequence[str] | None = None, out: Path = OUT) -> int:
    """The screens named, every one by default, into ``out``; each file written is named."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    system_fonts()
    for path in shoot(out, list(sys.argv[1:] if argv is None else argv) or SCREENS):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
