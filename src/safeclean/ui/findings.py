"""The Findings page: what the analysis found, grouped, filtered and selected, and quarantine
from the selection (decision 0014, items 4, 20, 21 and 26).

The findings are grouped by their strongest reason, each group with its files and size; level
filters and a search over the paths narrow what is shown. The detail of the current finding
shows its path, size, time, level and every reason, and Explain (local AI) (``ui.explain``).
What the analysis proposes at the Safe level is selected at first; a Review finding is selected
only by its own check box, a kept copy never: selecting a group or a level takes only what the
analysis proposes, and only what is shown. Moving asks first, runs as a task that acts, and
says what moved, what was refused and why; what moved leaves the list, the selection made stays
for the rest.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QWidget

from safeclean.analysis.report import AnalysisReport, Finding
from safeclean.analysis.score import Evidence, Level
from safeclean.quarantine.service import QuarantineResult
from safeclean.storage.pending import Domain
from safeclean.storage.session import SessionFailed
from safeclean.ui.dialogs import Confirmation
from safeclean.ui.explain import ExplainPanel
from safeclean.ui.parts import CheckBox, Head, Note, button, hbox, page, rows
from safeclean.ui.recovery import quarantine_lines
from safeclean.ui.sessions import Done, NoReliableCheck, Unfinished, in_quarantine
from safeclean.ui.tasks import Task

if TYPE_CHECKING:
    from safeclean.ui.window import Window

__all__ = ["FindingsPage"]

_PATH = Qt.ItemDataRole.UserRole  # a finding's item keeps its path; a group's, nothing
_EVIDENCE = Qt.ItemDataRole.UserRole + 1  # a group's item keeps its reason
_CHECKED, _UNCHECKED = Qt.CheckState.Checked, Qt.CheckState.Unchecked
_SELECTABLE = (Level.SAFE, Level.LIKELY_SAFE)  # never a whole Review level

Moving = Done[QuarantineResult] | Unfinished | NoReliableCheck | SessionFailed


def _children(group: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    return [item for index in range(group.childCount()) if (item := group.child(index)) is not None]


class FindingsPage(QWidget):
    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        self._findings: dict[str, Finding] = {}  # by path, in the analysis' order
        self._items: dict[str, QTreeWidgetItem] = {}
        self._syncing = False  # the page itself sets check states: no reaction to them
        translator = window.translator
        text = translator.text

        look = window.look
        self.filters = {level: CheckBox(look, translator.label(level)) for level in Level}
        for box in self.filters.values():
            box.setChecked(True)
            box.toggled.connect(self._filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText(text("findings.search"))
        self.search.setAccessibleName(text("findings.search"))
        self.search.textChanged.connect(self._filter)
        self.tree = QTreeWidget()
        rows(self.tree, look)
        self.tree.setAccessibleName(text("findings.tree"))
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([text(f"findings.{name}") for name in ("path", "level", "size")])
        self.tree.itemChanged.connect(self._changed)
        self.tree.currentItemChanged.connect(self._current)
        self.detail = Note(self)
        self.explain = ExplainPanel(window)
        self.select_buttons = {
            level: button(look, text("findings.select", level=translator.label(level)))
            for level in _SELECTABLE
        }
        for level, chosen in self.select_buttons.items():
            chosen.clicked.connect(lambda _=False, level=level: self._select(level))
        self.clear_button = button(look, text("findings.clear"))
        self.clear_button.clicked.connect(self._clear)
        self.bar = QLabel()
        self.move_button = button(look, text("findings.move"), role="primary")
        self.move_button.clicked.connect(self._move)
        self.result = Note(self)

        filters = hbox(spacing=16)
        for box in self.filters.values():
            filters.addWidget(box)
        filters.addWidget(self.search, 1)
        selection = hbox(spacing=8)
        for chosen in self.select_buttons.values():
            selection.addWidget(chosen)
        selection.addWidget(self.clear_button)
        selection.addStretch(1)
        selection.addWidget(self.bar)
        selection.addWidget(self.move_button)
        layout = page(self, Head(text("page.findings"), text("head.findings")))
        layout.addLayout(filters)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.detail)
        layout.addWidget(self.explain)
        layout.addLayout(selection)
        layout.addWidget(self.result)
        window.add_starter(self.move_button, lambda: bool(self.selected()))
        self._refresh()

    # --- what is listed ------------------------------------------------------------------------

    def show_analysis(self, analysis: AnalysisReport) -> None:
        """List the findings of a new analysis: what it proposes at the Safe level selected."""
        self._syncing = True
        self.tree.clear()
        self._findings = {str(finding.entry.path): finding for finding in analysis.findings}
        self._items = {}
        for evidence in Evidence:
            found = [f for f in analysis.findings if f.reasons[0].evidence is evidence]
            if found:
                self._add_group(evidence, found)
        self._syncing = False
        self.tree.expandAll()
        for column in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(column)
        self.result.clear()
        self._filter()
        self._refresh()
        self._window.sidebar.set_count("findings", len(self._findings))

    def _add_group(self, evidence: Evidence, found: list[Finding]) -> None:
        translator = self._window.translator
        group = QTreeWidgetItem(self.tree)
        group.setData(0, _EVIDENCE, evidence.value)
        group.setCheckState(0, _UNCHECKED)
        for finding in found:
            path = str(finding.entry.path)
            item = QTreeWidgetItem(group, [path, translator.label(finding.level)])
            item.setText(2, translator.size(finding.entry.size))
            item.setData(0, _PATH, path)
            if finding.keeps is None:
                preselected = finding.proposed and finding.level is Level.SAFE
                item.setCheckState(0, _CHECKED if preselected else _UNCHECKED)
            else:  # the copy that stays: never moved, so never selected
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self._items[path] = item

    def item(self, path: Path) -> QTreeWidgetItem:
        return self._items[str(path)]

    def findings(self) -> tuple[Finding, ...]:
        return tuple(self._findings.values())

    def selected(self) -> list[Finding]:
        """The findings checked, in the analysis' order."""
        return [
            finding
            for key, finding in self._findings.items()
            if self._items[key].checkState(0) == _CHECKED
        ]

    def _groups(self) -> list[QTreeWidgetItem]:
        return _children(self.tree.invisibleRootItem())

    def _finding(self, item: QTreeWidgetItem) -> Finding:
        return self._findings[item.data(0, _PATH)]

    # --- what is shown -------------------------------------------------------------------------

    def _filter(self) -> None:
        """A finding is shown when its level is and its path contains the search."""
        search = self.search.text().casefold()
        for group in self._groups():
            children = _children(group)
            for child in children:
                finding = self._finding(child)
                shown = self.filters[finding.level].isChecked()
                child.setHidden(not (shown and search in str(finding.entry.path).casefold()))
            group.setHidden(all(child.isHidden() for child in children))

    def _current(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:
        key = "" if current is None else current.data(0, _PATH)  # a group's: None
        finding = self._findings.get(key)
        self.detail.setText("" if finding is None else "\n".join(self._detail(finding)))
        self.explain.show_for(finding)

    def _detail(self, finding: Finding) -> list[str]:
        translator = self._window.translator
        text = translator.text
        entry = finding.entry
        moment = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.mtime_ns / 1e9))
        lines = [
            text("detail.path", path=entry.path),
            text("detail.size", size=translator.size(entry.size)),
            text("detail.modified", moment=moment),
            text("detail.level", level=translator.label(finding.level)),
        ]
        lines += [translator.reason(reason.evidence, reason.detail) for reason in finding.reasons]
        if finding.keeps is not None:
            lines.append(text("detail.kept"))
        return lines

    # --- the selection -------------------------------------------------------------------------

    def _proposals_shown(self, items: list[QTreeWidgetItem]) -> list[QTreeWidgetItem]:
        return [item for item in items if self._finding(item).proposed and not item.isHidden()]

    def _checkable(self, items: list[QTreeWidgetItem]) -> list[QTreeWidgetItem]:
        return [item for item in items if self._finding(item).keeps is None]

    def _set(self, items: list[QTreeWidgetItem], state: Qt.CheckState) -> None:
        self._syncing = True
        for item in items:
            item.setCheckState(0, state)
        self._syncing = False

    def _changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._syncing:
            return
        if item.parent() is None:  # a group: what it proposes and shows, or nothing of it
            children = _children(item)
            if item.checkState(0) == _CHECKED:
                self._set(self._proposals_shown(children), _CHECKED)
            else:
                self._set(self._checkable(children), _UNCHECKED)
        self._refresh()

    def _select(self, level: Level) -> None:
        shown = self._proposals_shown(list(self._items.values()))
        self._set([item for item in shown if self._finding(item).level is level], _CHECKED)
        self._refresh()

    def _clear(self) -> None:
        self._set(self._checkable(list(self._items.values())), _UNCHECKED)
        self._refresh()

    def _amount(self, findings: list[Finding]) -> dict[str, str]:
        translator = self._window.translator
        return {
            "files": translator.count("file", len(findings)),
            "size": translator.size(sum(finding.entry.size for finding in findings)),
        }

    def _refresh(self) -> None:
        """Each group's files, size and check state; the selection's files and size."""
        translator = self._window.translator
        self._syncing = True
        for group in self._groups():
            children = _children(group)
            reason = translator.label(Evidence(group.data(0, _EVIDENCE)))
            amount = self._amount([self._finding(child) for child in children])
            group.setText(0, translator.text("findings.group", reason=reason, **amount))
            checkable = self._checkable(children)
            checked = sum(1 for child in checkable if child.checkState(0) == _CHECKED)
            whole = _CHECKED if checked == len(checkable) else Qt.CheckState.PartiallyChecked
            group.setCheckState(0, _UNCHECKED if checked == 0 else whole)
        self._syncing = False
        self.bar.setText(translator.text("findings.selected", **self._amount(self.selected())))
        self._window.update_starters()

    # --- moving to the quarantine --------------------------------------------------------------

    def _move(self) -> None:
        window, translator = self._window, self._window.translator
        chosen = self.selected()
        action = translator.text("findings.move")
        asked = Confirmation(
            title=action,
            text=translator.text("move.confirm", **self._amount(chosen)),
            details=tuple(str(finding.entry.path) for finding in chosen),
            action=action,
        )
        if not window.dialogs.confirm(asked):
            return
        candidates = [finding.candidate for finding in chosen]
        environment = window.environment

        def work() -> Moving:
            context = environment.scan_context()
            return in_quarantine(context, lambda service: service.quarantine(candidates))

        window.run(Task(translator.text("task.quarantine"), work, self._moved, acts=True))

    def _moved(self, outcome: Moving) -> None:
        window, translator = self._window, self._window.translator
        if not isinstance(outcome, Done):
            self.result.setText(window.refusal(outcome))
            return
        window.recovery.report(Domain.QUARANTINE, quarantine_lines(translator, outcome.recovered))
        result = outcome.result
        gone = {str(moved.original) for moved in result.moved}
        lines = [
            translator.text("move.moved", **self._amount([self._findings[key] for key in gone]))
        ]
        if result.error:
            lines.append(translator.text("move.stopped", error=result.error))
        lines += [
            translator.text(
                "move.refused",
                path=refused.path,
                reason=translator.reason(refused.reason, refused.detail),
            )
            for refused in result.refused
        ]
        self.result.setText("\n".join(lines))
        self._remove(gone)
        self._refresh()

    def _remove(self, gone: set[str]) -> None:
        """What moved leaves the list, and a group left empty with it."""
        root = self.tree.invisibleRootItem()
        for group in self._groups():
            for child in _children(group):
                if child.data(0, _PATH) in gone:
                    group.removeChild(child)
            if group.childCount() == 0:
                root.removeChild(group)
        for key in gone:
            del self._findings[key]
            del self._items[key]
        self._window.sidebar.set_count("findings", len(self._findings))
