"""The Overview page: the scan card, what the last scan found, and a card each for Quarantine,
Organize and Autostart (decision 0014, items 19 and 48).

The folders are the safe zones at first, each a chip with its path from the home folder (``~``);
the user adds folders of their own, and removes them again with their chip's remove button,
never a safe zone. Scan now reads only, in a worker: it walks the folders, hashes what may be
duplicated and rates every file. The scan card then says when the scan ran, the files it read,
the duplicate groups and the paths skipped, and the page says when files in use cannot be
recognized on this system. A card per level shows its size, its files and their strongest
reasons, and opens Findings with that level only; the findings go to the Findings page. The
cards of Quarantine, Organize and Autostart say what the window last read there, or what the
page does, and open their page on a click, Enter or Space.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

from safeclean.analysis.report import AnalysisReport
from safeclean.analysis.run import analyze_paths
from safeclean.analysis.score import Evidence, Level
from safeclean.analysis.size_age import Thresholds
from safeclean.core.scanner import ScanReport
from safeclean.environment import Environment
from safeclean.organize.planner import Plan
from safeclean.ui.i18n import Translator
from safeclean.ui.parts import (
    Head,
    Icon,
    Note,
    button,
    card,
    divider,
    dot,
    hbox,
    link,
    page,
    shares,
    surface2_tile,
    text_ink,
    vbox,
)
from safeclean.ui.shown import moment, shown_path
from safeclean.ui.sidebar import ICONS
from safeclean.ui.tasks import Task
from safeclean.ui.theme import Look

if TYPE_CHECKING:
    from safeclean.ui.window import Window

__all__ = [
    "FolderChip",
    "LevelCard",
    "OverviewPage",
    "Scanned",
    "ServiceCard",
    "scan",
]

SERVICES = ("quarantine", "organize", "autostart")
_OPENS = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)


def _lower(label: str) -> str:
    return label[:1].lower() + label[1:]


@dataclass(frozen=True)
class Scanned:
    """What one scan of ``roots`` found; ``checked``: open files are recognized on this system;
    ``at``: when the scan started, in seconds since the epoch."""

    report: ScanReport
    analysis: AnalysisReport
    checked: bool
    at: float
    roots: list[Path]


def scan(environment: Environment, roots: list[Path]) -> Scanned:
    """In the worker: the context of the system, the scan and the rating."""
    at = time.time()
    context = environment.scan_context()
    report, analysis = analyze_paths([str(root) for root in roots], context, Thresholds())
    return Scanned(report, analysis, context.open_files_checked, at, list(roots))


class FolderChip(QFrame):
    """A folder to scan: the folder icon and its path; an added folder's with a remove button
    (``remove``, named ``removal``)."""

    def __init__(self, look: Look, path: Path, shown: str, removal: str | None) -> None:
        super().__init__()
        self.path = path
        self.setProperty("role", "chip")
        self.setToolTip(str(path))
        self.setFixedHeight(36)
        self.icon = Icon(look, "folder", text_ink, size=16)
        self.label = QLabel(shown)
        self.remove: QPushButton | None = None
        layout = hbox(self, margins=(12, 0, 12 if removal is None else 8, 0), spacing=8)
        layout.addWidget(self.icon)
        layout.addWidget(self.label)
        if removal is not None:
            self.remove = button(look, "", role="icon", icon="x")
            self.remove.setFixedSize(20, 20)
            self.remove.setAccessibleName(removal)
            self.remove.setToolTip(removal)
            layout.addWidget(self.remove)


class LevelCard(QFrame):
    """A level after a scan: its dot and label, its size (``amount``), its files and their
    strongest reasons, and the link that opens Findings with this level only."""

    def __init__(self, translator: Translator, level: Level) -> None:
        super().__init__()
        self.setProperty("role", "card")
        shares(self)
        self.dot = dot(level.value)
        self.name = QLabel(translator.label(level))
        self.name.setProperty("role", "strong")
        self.amount = QLabel()
        self.amount.setProperty("role", "figure")
        self.files = Note(self, role="secondary")
        key = "overview.open_review" if level is Level.REVIEW else "overview.open_level"
        self.link = link(translator.text(key))
        named = hbox(spacing=8)
        named.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        named.addWidget(self.name, 1)
        layout = vbox(self, margins=(20, 20, 20, 20), spacing=8)
        layout.addLayout(named)
        layout.addWidget(self.amount)
        layout.addWidget(self.files)
        layout.addStretch(1)
        layout.addWidget(self.link, 0, Qt.AlignmentFlag.AlignLeft)


class ServiceCard(QFrame):
    """A page beside the scan: its icon and name, what the window last read there or what the
    page does; a click on it, or Enter or Space, opens it (``opened``)."""

    opened = Signal()

    def __init__(self, look: Look, name: str, icon: str) -> None:
        super().__init__()
        self.setProperty("role", "card")
        shares(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(name)
        self.icon = Icon(look, icon, text_ink, size=18, tile=surface2_tile, side=32)
        self.name = QLabel(name)
        self.name.setProperty("role", "caption")
        self.main = QLabel()
        self.main.setProperty("role", "strong")
        self.main.setWordWrap(True)
        self.note = Note(self, role="secondary")
        words = vbox(spacing=4)
        words.addWidget(self.name)
        words.addWidget(self.main)
        words.addWidget(self.note)
        words.addStretch(1)
        layout = hbox(self, margins=(20, 16, 20, 16), spacing=16)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(words, 1)

    def say(self, main: str, note: str) -> None:
        self.main.setText(main)
        self.note.setText(note)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        inside = self.rect().contains(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and inside:
            self.opened.emit()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in _OPENS:
            self.opened.emit()
            return
        super().keyPressEvent(event)


class OverviewPage(QWidget):
    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        translator = window.translator
        text = translator.text
        look = window.look
        self._zones = [
            Path(zone) for zone in window.environment.scan_context().policy.default_roots()
        ]
        self._added: list[Path] = []
        self._chips: list[FolderChip] = []
        self.scanned: Scanned | None = None

        self.scan_card, inside = card(surface=True)
        self.scan_title = QLabel(text("overview.scan_title"))
        self.scan_title.setProperty("role", "card-title")
        self.scan_text = QLabel(text("overview.read_only"))
        self.scan_text.setProperty("role", "secondary")
        self.scan_text.setWordWrap(True)
        self.scan_button = button(look, text("overview.scan"), role="primary", icon="refresh-cw")
        self.scan_button.clicked.connect(self.start_scan)
        window.add_starter(self.scan_button)
        self.add_button = button(look, text("overview.add"), role="plain", icon="plus")
        self.add_button.clicked.connect(self._add)
        self.last = Note(self, text("overview.none"), role="caption")
        words = vbox(spacing=4)
        words.addWidget(self.scan_title)
        words.addWidget(self.scan_text)
        top = hbox(spacing=16)
        top.addLayout(words, 1)
        top.addWidget(self.scan_button, 0, Qt.AlignmentFlag.AlignTop)
        self._row = hbox(spacing=8)
        self._row.addWidget(self.add_button)
        self._row.addStretch(1)
        inside.addLayout(top)
        inside.addSpacing(8)
        inside.addLayout(self._row)
        inside.addSpacing(4)
        inside.addWidget(divider())
        inside.addSpacing(4)
        inside.addWidget(self.last)
        for zone in self._zones:
            self._chip(zone, removable=False)

        self.unreliable = QLabel(text("overview.unreliable"))
        self.unreliable.setWordWrap(True)
        self.unreliable.setProperty("role", "accent")
        self.unreliable.hide()

        self.level_cards = QWidget()
        self.levels = {level: LevelCard(translator, level) for level in Level}
        levels = hbox(self.level_cards, spacing=16)
        for level, shown in self.levels.items():
            shown.link.clicked.connect(lambda _=False, level=level: self._open_level(level))
            levels.addWidget(shown, 1)
        self.level_cards.hide()

        self.services = {
            name: ServiceCard(look, text(f"page.{name}"), ICONS[name]) for name in SERVICES
        }
        services = hbox(spacing=16)
        for name, service in self.services.items():
            service.opened.connect(lambda name=name: window.show_page(name))
            services.addWidget(service, 1)
        self.show_quarantine(None)
        self.show_plan(None)
        self.show_autostart(None)

        layout = page(self, _head(translator))
        layout.addWidget(self.scan_card)
        layout.addWidget(self.unreliable)
        layout.addSpacing(8)
        layout.addWidget(self.level_cards)
        layout.addLayout(services)
        layout.addStretch(1)

    # --- the folders ---------------------------------------------------------------------------

    def roots(self) -> list[Path]:
        """The safe zones, then the folders added."""
        return [*self._zones, *self._added]

    def chips(self) -> list[FolderChip]:
        return list(self._chips)

    def _chip(self, folder: Path, *, removable: bool) -> None:
        translator = self._window.translator
        shown = shown_path(folder, Path.home())
        removal = translator.text("overview.remove", folder=shown) if removable else None
        made = FolderChip(self._window.look, folder, shown, removal)
        if made.remove is not None:
            made.remove.clicked.connect(lambda _=False: self._remove(made))
        self._row.insertWidget(len(self._chips), made)
        self._chips.append(made)

    def _add(self) -> None:
        folder = self._window.dialogs.choose_folder()
        if folder is None or folder in self.roots():
            return
        self._added.append(folder)
        self._chip(folder, removable=True)

    def _remove(self, chip: FolderChip) -> None:
        self._added.remove(chip.path)
        self._chips.remove(chip)
        self._row.removeWidget(chip)
        chip.setParent(None)

    # --- the scan ------------------------------------------------------------------------------

    def start_scan(self) -> None:
        """Scan the folders shown, as Scan now does."""
        window, roots = self._window, self.roots()
        title = window.translator.text("task.scan")
        window.run(Task(title, lambda: scan(window.environment, roots), self._scanned))

    def _scanned(self, scanned: Scanned) -> None:
        translator = self._window.translator
        text, count = translator.text, translator.count
        self.scanned = scanned
        report, analysis = scanned.report, scanned.analysis
        self.last.setText(
            text(
                "overview.last",
                moment=moment(scanned.at),
                files=count("file", report.files_scanned),
                groups=count("group", len(analysis.duplicates)),
                paths=count("path", len(report.skipped)),
            )
        )
        for total in analysis.totals:
            shown = self.levels[total.level]
            shown.amount.setText(translator.size(total.bytes))
            shown.files.setText(_files(translator, analysis, total.level, total.files))
        self.level_cards.show()
        self.unreliable.setHidden(scanned.checked)
        self._window.findings.show_analysis(analysis, scanned.roots, scanned.at)

    def _open_level(self, level: Level) -> None:
        self._window.findings.show_only(level)
        self._window.show_page("findings")

    # --- what the window last read of the other pages ------------------------------------------

    def show_quarantine(self, read: tuple[int, int] | None) -> None:
        """``read``: the files the window last read in the quarantine and their size."""
        translator = self._window.translator
        text = translator.text
        main = text("overview.quarantine")
        if read is not None:
            files, size = read
            main = text(
                "overview.quarantine_read",
                files=translator.count("file", files),
                size=translator.size(size),
            )
        self.services["quarantine"].say(main, text("overview.quarantine_note"))

    def show_plan(self, plan: Plan | None) -> None:
        """The plan the Organize page last made; ``None`` once there is none."""
        translator = self._window.translator
        text = translator.text
        shown = self.services["organize"]
        if plan is None:
            shown.say(text("overview.organize"), text("overview.organize_note"))
            return
        folder = shown_path(plan.folder, Path.home())
        main = text(
            "overview.organize_read", files=translator.count("file", len(plan.moves)), folder=folder
        )
        folders = len({move.category for move in plan.moves})
        note = (
            text("overview.organize_into", folders=translator.count("folder", folders))
            if folders
            else text("overview.organize_nothing")
        )
        shown.say(main, note)

    def show_autostart(self, read: tuple[int, int] | None) -> None:
        """``read``: the entries the window last read, and how many of them are off."""
        translator = self._window.translator
        text = translator.text
        shown = self.services["autostart"]
        if read is None:
            shown.say(text("overview.autostart"), text("overview.autostart_note"))
            return
        entries, off = read
        shown.say(translator.count("entry", entries), text("overview.autostart_off", n=off))


def _head(translator: Translator) -> Head:
    return Head(translator.text("page.overview"), translator.text("head.overview"))


def _files(translator: Translator, analysis: AnalysisReport, level: Level, files: int) -> str:
    """A level's files and their strongest reasons, in the order of Findings' groups."""
    strongest = {
        finding.reasons[0].evidence for finding in analysis.findings if finding.level is level
    }
    reasons = ", ".join(
        _lower(translator.label(evidence)) for evidence in Evidence if evidence in strongest
    )
    counted = translator.count("file", files)
    line = (
        translator.text("overview.reasons", files=counted, reasons=reasons) if reasons else counted
    )
    return translator.text("overview.never", files=line) if level is Level.REVIEW else line
