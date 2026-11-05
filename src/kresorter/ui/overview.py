"""The Overview page: the scan card, what the last scan found, and a card each for Quarantine,
Organize, Autostart and the local AI (decision 0014, items 19 and 48; 0018, item 35).

The folders are the safe zones at first, each a chip with its path from the home folder (``~``),
and on Windows the programs' caches, one chip for their folders, read for junk only (0020 item
15); the user adds folders of their own, and removes them again with their chip's remove
button, never a safe zone. Scan now reads only, in a worker: it walks the folders, hashes what
may be duplicated and rates every file. The scan card then says when the scan ran, the files it
read, the duplicate groups and the paths skipped, and the page says when files in use cannot be
recognized on this system. A card per level shows its size, its files and their strongest
reasons, and opens Findings with that level only; the findings go to the Findings page. The
cards of Quarantine, Organize and Autostart say what the window last read there, or what the
page does, and open their page on a click, Enter or Space. The local AI's names the model in use
and says whether the last Check found it available, unavailable, or that none ran yet; it opens
Settings, and asks nothing of Ollama (0013 item 1).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QPushButton, QWidget

from kresorter.analysis.report import AnalysisReport
from kresorter.analysis.run import analyze_paths
from kresorter.analysis.score import Evidence, Level
from kresorter.analysis.size_age import Thresholds
from kresorter.core.policy import CACHES
from kresorter.core.scanner import Progress, ScanReport
from kresorter.environment import Environment
from kresorter.organize.planner import Plan
from kresorter.ui.i18n import Translator
from kresorter.ui.motion import Bar
from kresorter.ui.parts import (
    Head,
    Icon,
    Label,
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
    tooltip,
    vbox,
)
from kresorter.ui.shown import moment, shown_path
from kresorter.ui.sidebar import ICONS
from kresorter.ui.tasks import Read, Task
from kresorter.ui.theme import Look

if TYPE_CHECKING:
    from kresorter.ui.window import Window

__all__ = [
    "FolderChip",
    "LevelCard",
    "OverviewPage",
    "Scanned",
    "ServiceCard",
    "scan",
]

SERVICES = {  # a card, and the page it opens
    "quarantine": "quarantine",
    "organize": "organize",
    "autostart": "autostart",
    "ai": "settings",
}
_TITLES = {"ai": "overview.ai_title"}  # otherwise the page's name
_ICONS = {**ICONS, "ai": "sparkles"}
_CHECKED = {None: "overview.ai_not_checked", True: "overview.ai_available"}
_OPENS = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)


def _lower(label: str) -> str:
    return label[:1].lower() + label[1:]


@dataclass(frozen=True)
class Scanned:
    """What one scan of ``roots`` found, and of the programs' caches when ``caches``;
    ``checked``: open files are recognized on this system; ``at``: when the scan started, in
    seconds since the epoch."""

    report: ScanReport
    analysis: AnalysisReport
    checked: bool
    at: float
    roots: list[Path]
    caches: bool = False


def scan(
    environment: Environment, roots: list[Path], junk_only: list[Path], read: Progress
) -> Scanned:
    """In the worker: the context of the system, the scan of ``roots``, and of ``junk_only``
    for junk only, and the rating; ``read`` counts the files read so far."""
    at = time.time()
    context = environment.scan_context()
    paths = [str(root) for root in roots]
    report, analysis = analyze_paths(
        paths, context, Thresholds(), junk_only=junk_only, progress=read
    )
    return Scanned(report, analysis, context.open_files_checked, at, list(roots), bool(junk_only))


class FolderChip(QFrame):
    """A folder to scan: the folder icon and its path, and a remove button (``remove``, named
    ``removal``): a safe zone's leaves it out (decision 0018, item 17). Its tooltip is its
    path, or ``tip``: the programs' caches' names their folders (decision 0020, item 15)."""

    def __init__(
        self, look: Look, path: Path, shown: str, removal: str, tip: str | None = None
    ) -> None:
        super().__init__()
        self.path = path
        self.setProperty("role", "chip")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)  # its border shows the pointer over it
        self.setToolTip(tooltip(str(path) if tip is None else tip))
        self.setFixedHeight(36)
        self.icon = Icon(look, "folder", text_ink, size=16)
        self.label = Label(shown)
        layout = hbox(self, margins=(12, 0, 8, 0), spacing=8)
        layout.addWidget(self.icon)
        layout.addWidget(self.label)
        self.remove = button(look, "", role="icon", icon="x")
        self.remove.setFixedSize(20, 20)
        self.remove.setAccessibleName(removal)
        self.remove.setToolTip(tooltip(removal))
        layout.addWidget(self.remove)


class LevelCard(QFrame):
    """A level after a scan: its dot and label, its size (``amount``), its files and their
    strongest reasons, and the link that opens Findings with this level only."""

    def __init__(self, translator: Translator, level: Level) -> None:
        super().__init__()
        self.setProperty("role", "card")
        shares(self)
        self.dot = dot(level.value)
        self.name = Label(translator.label(level))
        self.name.setProperty("role", "strong")
        self.amount = Label()
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
        self.setProperty("opens", True)  # its border shows the pointer over it
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        shares(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(name)
        self.icon = Icon(look, icon, text_ink, size=18, tile=surface2_tile, side=32)
        self.name = Label(name)
        self.name.setProperty("role", "caption")
        self.main = Label()
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
        policy = window.environment.scan_context().policy
        self._caches = [Path(folder) for folder in policy.cache_zone()]
        # The programs' caches stand as one zone, after the safe zones (0020, item 15).
        caches = [Path(CACHES)] if self._caches else []
        self._zones = [*(Path(zone) for zone in policy.default_roots()), *caches]
        self._skipped = set(window.settings.current.skipped_zones)  # by name (0018, item 17)
        self._added: list[Path] = []
        self._chips: list[FolderChip] = []
        self._zone_links: dict[Path, QPushButton] = {}
        self.scanned: Scanned | None = None

        self.scan_card, inside = card(surface=True)
        self.scan_title = Label(text("overview.scan_title"))
        self.scan_title.setProperty("role", "card-title")
        self.scan_text = Label(text("overview.read_only"))
        self.scan_text.setProperty("role", "secondary")
        self.scan_text.setWordWrap(True)
        self.scan_button = button(look, text("overview.scan"), role="primary", icon="refresh-cw")
        self.scan_button.clicked.connect(self.start_scan)
        window.add_starter(self.scan_button, lambda: bool(self.roots() or self.junk_only()))
        self.add_button = button(look, text("overview.add"), role="plain", icon="plus")
        self.add_button.clicked.connect(self._add)
        self.last = Note(self, text("overview.none"), role="caption")
        self.scan_bar = Bar(look)  # while a scan runs (decision 0018, item 9)
        window.tasks.busy.connect(self._busy)
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
        inside.addWidget(self.scan_bar)
        inside.addSpacing(8)
        inside.addLayout(self._row)
        inside.addSpacing(4)
        inside.addWidget(divider())
        inside.addSpacing(4)
        inside.addWidget(self.last)
        for zone in self._zones:
            if zone.name in self._skipped:
                self._zone_link(zone)
            else:
                self._chip(zone, zone=True)

        self.unreliable = Label(text("overview.unreliable"))
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
            name: ServiceCard(look, text(_TITLES.get(name, f"page.{name}")), _ICONS[name])
            for name in SERVICES
        }
        services = hbox(spacing=16)
        for name, service in self.services.items():
            service.opened.connect(lambda opens=SERVICES[name]: window.show_page(opens))
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
        """The safe zones not left out, then the folders added."""
        return [*(z for z in self._shown_zones() if not self._is_caches(z)), *self._added]

    def junk_only(self) -> list[Path]:
        """The folders of the programs' caches unless they are left out, read for junk only."""
        return list(self._caches) if any(map(self._is_caches, self._shown_zones())) else []

    def chips(self) -> list[FolderChip]:
        return list(self._chips)

    def zone_links(self) -> list[QPushButton]:
        """The links that put the zones left out back, in the order of the zones."""
        return [self._zone_links[zone] for zone in self._zones if zone in self._zone_links]

    def _shown_zones(self) -> list[Path]:
        return [zone for zone in self._zones if zone.name not in self._skipped]

    def _is_caches(self, zone: Path) -> bool:
        return bool(self._caches) and zone == self._zones[-1]

    def _shown(self, folder: Path) -> str:
        """A folder from the home folder; the programs' caches by their name."""
        if self._is_caches(folder):
            return self._window.translator.text("overview.caches")
        return shown_path(folder, Path.home())

    def _chip(self, folder: Path, *, zone: bool) -> None:
        """A chip with its remove button: a zone's leaves it out, an added folder's removes it.
        In the row, a zone's sits among the zones in their order, before the folders added."""
        translator = self._window.translator
        shown = self._shown(folder)
        removal = translator.text("overview.skip" if zone else "overview.remove", folder=shown)
        tip = None
        if zone and self._is_caches(folder):
            tip = "\n".join([translator.text("overview.caches_tip"), *map(str, self._caches)])
        made = FolderChip(self._window.look, folder, shown, removal, tip)
        leave = self._skip if zone else self._remove
        made.remove.clicked.connect(lambda _=False: leave(made))
        index = self._shown_zones().index(folder) if zone else len(self._chips)
        self._row.insertWidget(index, made)
        self._chips.insert(index, made)

    def _zone_link(self, zone: Path) -> None:
        """The link that puts ``zone`` back, after Add folder, among the others in the order of
        the zones (decision 0018, item 18)."""
        shown = self._shown(zone)
        text = self._window.translator.text
        made = link(text("overview.zone_link", folder=shown))
        made.setToolTip(tooltip(text("overview.put_back", folder=shown)))
        made.setAccessibleName(made.toolTip())
        made.clicked.connect(lambda _=False: self._put_back(zone))
        self._zone_links[zone] = made
        index = self.zone_links().index(made)
        self._row.insertWidget(len(self._chips) + 1 + index, made)

    def _add(self) -> None:
        folder = self._window.dialogs.choose_folder()
        if folder is None or folder in self.roots():
            return
        if folder in self._zone_links:  # a zone left out: put back where it was
            self._put_back(folder)
            return
        self._added.append(folder)
        self._chip(folder, zone=False)
        self._window.update_starters()

    def _remove(self, chip: FolderChip) -> None:
        self._added.remove(chip.path)
        self._drop(chip)

    def _drop(self, chip: FolderChip) -> None:
        self._chips.remove(chip)
        self._row.removeWidget(chip)
        chip.setParent(None)
        self._window.update_starters()

    def _skip(self, chip: FolderChip) -> None:
        """Leave a zone out, once the window remembers it."""
        if self._remember(self._skipped | {chip.path.name}):
            self._drop(chip)
            self._zone_link(chip.path)

    def _put_back(self, zone: Path) -> None:
        if self._remember(self._skipped - {zone.name}):
            made = self._zone_links.pop(zone)
            self._row.removeWidget(made)
            made.setParent(None)
            self._chip(zone, zone=True)
            self._window.update_starters()

    def _remember(self, skipped: set[str]) -> bool:
        """The zones left out saved in the settings; the window says why when they are not."""
        window = self._window
        names = tuple(zone.name for zone in self._zones if zone.name in skipped)
        refused = window.settings.remember(replace(window.settings.current, skipped_zones=names))
        if refused is not None:
            window.message.setText(refused)
            return False
        self._skipped = set(names)
        return True

    # --- the scan ------------------------------------------------------------------------------

    def start_scan(self) -> None:
        """Scan the folders shown, as Scan now does."""
        window, roots, read = self._window, self.roots(), Read()
        title = window.translator.text("task.scan")
        work = partial(scan, window.environment, roots, self.junk_only(), read)
        if window.run(Task(title, work, self._scanned, read=read)):
            self.scan_bar.run()

    def _busy(self, running: bool) -> None:
        """The scan's bar stops once no task runs, the scan's having ended or failed."""
        if not running:
            self.scan_bar.stop()

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
        self._window.findings.show_analysis(
            analysis, scanned.roots, scanned.at, caches=scanned.caches
        )

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

    def show_ai(self, model: str, checked: bool | None) -> None:
        """``model``: the model in use as the window says it; ``checked`` as the last Check
        found the local AI, ``None`` before any."""
        key = _CHECKED.get(checked, "overview.ai_unavailable")
        self.services["ai"].say(model, self._window.translator.text(key))


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
