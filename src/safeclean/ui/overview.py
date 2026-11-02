"""The Overview page: the folders to scan, Scan, and what the scan found (decision 0014,
item 19).

The folders are the safe zones at first; the user adds folders of their own, and removes them
again, never a safe zone. Scan reads only, in a worker: it walks the folders, hashes what may
be duplicated and rates every file. The page then shows each level's files and size, the
duplicate groups and the paths skipped, and says when files in use cannot be recognized on
this system; the findings go to the Findings page.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from safeclean.analysis.report import AnalysisReport
from safeclean.analysis.run import analyze_paths
from safeclean.analysis.score import Level
from safeclean.analysis.size_age import Thresholds
from safeclean.core.scanner import ScanReport
from safeclean.environment import Environment
from safeclean.ui.tasks import Task

if TYPE_CHECKING:
    from safeclean.ui.window import Window

__all__ = ["OverviewPage", "Scanned", "scan"]


@dataclass(frozen=True)
class Scanned:
    """What one scan found; ``checked``: open files are recognized on this system."""

    report: ScanReport
    analysis: AnalysisReport
    checked: bool


def scan(environment: Environment, roots: list[Path]) -> Scanned:
    """In the worker: the context of the system, the scan and the rating."""
    context = environment.scan_context()
    report, analysis = analyze_paths([str(root) for root in roots], context, Thresholds())
    return Scanned(report, analysis, context.open_files_checked)


def _label(role: str = "") -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setProperty("role", role)
    return label


class OverviewPage(QWidget):
    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        text = window.translator.text
        self._zones = [
            Path(zone) for zone in window.environment.scan_context().policy.default_roots()
        ]
        self._added: list[Path] = []

        heading = QLabel(text("page.overview"))
        heading.setProperty("role", "heading")
        self.folders = QListWidget()
        self.folders.setAccessibleName(text("overview.folders"))
        self.folders.addItems([str(zone) for zone in self._zones])
        self.folders.currentRowChanged.connect(self._current)
        self.add_button = QPushButton(text("overview.add"))
        self.add_button.clicked.connect(self._add)
        self.remove_button = QPushButton(text("overview.remove"))
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self._remove)
        self.scan_button = QPushButton(text("overview.scan"))
        self.scan_button.setProperty("role", "primary")
        self.scan_button.clicked.connect(self._scan)
        window.add_starter(self.scan_button)

        self.state = _label("secondary")
        self.state.setText(text("overview.none"))
        self.summary = QWidget()
        self.levels = {level: _label() for level in Level}
        self.duplicates = _label()
        self.skipped = _label()
        lines = QVBoxLayout(self.summary)
        lines.setContentsMargins(0, 0, 0, 0)
        for level, label in self.levels.items():
            label.setProperty("badge", level.value)
            lines.addWidget(label)
        lines.addWidget(self.duplicates)
        lines.addWidget(self.skipped)
        self.summary.hide()
        self.unreliable = _label("accent")
        self.unreliable.setText(text("overview.unreliable"))
        self.unreliable.hide()

        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        buttons.addWidget(self.scan_button)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(self.folders, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.state)
        layout.addWidget(self.summary)
        layout.addWidget(self.unreliable)
        layout.addStretch(1)

    def roots(self) -> list[Path]:
        """The safe zones, then the folders added."""
        return [*self._zones, *self._added]

    def _current(self, row: int) -> None:
        self.remove_button.setEnabled(row >= len(self._zones))

    def _add(self) -> None:
        folder = self._window.dialogs.choose_folder()
        if folder is None or folder in self.roots():
            return
        self._added.append(folder)
        self.folders.addItem(str(folder))

    def _remove(self) -> None:
        row = self.folders.currentRow()
        del self._added[row - len(self._zones)]
        self.folders.takeItem(row)

    def _scan(self) -> None:
        window, roots = self._window, self.roots()
        title = window.translator.text("task.scan")
        window.run(Task(title, lambda: scan(window.environment, roots), self._scanned))

    def _scanned(self, scanned: Scanned) -> None:
        translator = self._window.translator
        for total in scanned.analysis.totals:
            files, size = translator.count("file", total.files), translator.size(total.bytes)
            label = translator.label(total.level)
            self.levels[total.level].setText(
                translator.text("overview.level", level=label, files=files, size=size)
            )
        groups = len(scanned.analysis.duplicates)
        self.duplicates.setText(translator.text("overview.duplicates", n=groups))
        self.skipped.setText(translator.text("overview.skipped", n=len(scanned.report.skipped)))
        self.state.clear()
        self.summary.show()
        self.unreliable.setHidden(scanned.checked)
        self._window.findings.show_analysis(scanned.analysis)
