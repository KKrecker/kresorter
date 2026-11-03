"""The Findings page: what the analysis found, grouped, filtered and selected, and quarantine
from the selection (decision 0014, items 4, 20, 21, 26 and 49).

The head says which folders were scanned and when, with Rescan. The findings are grouped by
their strongest reason, each group with its files, its rules and its size; a chip per level and
a search over the paths narrow what is shown. The detail at the right shows the current
finding's level, name, folder, size, time and the scanned folder it was found in, every reason,
and the explanation card (``ui.explain``). What the analysis proposes at the Safe level is
selected at first; a Review finding is selected only by its own check box, a kept copy never:
selecting a group or a level takes only what the analysis proposes, and only what is shown.
Moving asks first, runs as a task that acts, and says what moved, what was refused and why;
what moved leaves the list, the selection made stays for the rest.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QTreeWidget, QTreeWidgetItem, QWidget

from safeclean.analysis.report import AnalysisReport, Finding
from safeclean.analysis.score import Evidence, Level
from safeclean.quarantine.service import QuarantineResult
from safeclean.storage.pending import Domain
from safeclean.storage.session import SessionFailed
from safeclean.ui.dialogs import Confirmation
from safeclean.ui.explain import ExplainPanel
from safeclean.ui.parts import (
    BADGE,
    EMPHASIS,
    QUIET,
    SECONDARY,
    Field,
    Head,
    Note,
    badge,
    bar,
    button,
    chip,
    divider,
    hbox,
    link,
    rows,
    vbox,
)
from safeclean.ui.recovery import quarantine_lines
from safeclean.ui.sessions import Done, NoReliableCheck, Unfinished, in_quarantine
from safeclean.ui.shown import moment, shown_path
from safeclean.ui.tasks import Task

if TYPE_CHECKING:
    from safeclean.ui.i18n import Translator
    from safeclean.ui.window import Window

__all__ = ["DETAIL_WIDTH", "SEARCH_WIDTHS", "FindingDetail", "FindingsPage"]

DETAIL_WIDTH = 320  # px: the detail at the page's right
SEARCH_WIDTHS = (160, 240)  # px: the search field's, as it shares its row with the chips
PATH = Qt.ItemDataRole.UserRole  # a finding's item keeps its path; a group's, nothing
_EVIDENCE = Qt.ItemDataRole.UserRole + 1  # a group's item keeps its reason
_CHECKED, _UNCHECKED = Qt.CheckState.Checked, Qt.CheckState.Unchecked
_SELECTABLE = (Level.SAFE, Level.LIKELY_SAFE)  # never a whole Review level
_NAME, _SIZE, _LEVEL = range(3)  # the columns
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_FACTS = ("size", "modified", "found")
_JUNK = frozenset(
    {
        Evidence.JUNK_CACHE,
        Evidence.JUNK_THUMBNAILS,
        Evidence.JUNK_OS_METADATA,
        Evidence.JUNK_TEMP,
        Evidence.JUNK_CRASH_DUMP,
    }
)  # a reason of these names its rule

Moving = Done[QuarantineResult] | Unfinished | NoReliableCheck | SessionFailed


def _children(group: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    return [item for index in range(group.childCount()) if (item := group.child(index)) is not None]


def folders(translator: Translator, roots: list[Path]) -> str:
    """The folders scanned, from the home folder as ``~``, the last after "and"."""
    shown = [shown_path(root, Path.home()) for root in roots]
    if len(shown) < 2:
        return "".join(shown)
    return translator.text("list.and", first=", ".join(shown[:-1]), last=shown[-1])


def found_in(path: Path, roots: list[Path]) -> Path:
    """The scanned folder ``path`` is in: the deepest that holds it, its folder otherwise."""
    holding = [root for root in roots if path.is_relative_to(root)]
    return max(holding, key=lambda root: len(root.parts), default=path.parent)


class FindingDetail(QFrame):
    """The detail at the page's right (320 px, a border at its left): the current finding's
    level as a badge, its name in semibold and its folder, then its size, its time and the
    scanned folder it was found in (``facts``), "Why" with every reason (``why``), and the
    explanation card (``explain``); with no finding, that choosing one shows them (``none``)."""

    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        text = window.translator.text
        self.setProperty("role", "side")
        self.setFixedWidth(DETAIL_WIDTH)
        self.none = Note(self, text("detail.none"), role="secondary")
        self.content = QWidget()
        self.badge = badge("", Level.SAFE.value)
        self.name = QLabel()
        self.name.setProperty("role", "card-title")
        self.name.setWordWrap(True)
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder = Note(self, role="secondary")
        self.labels = {fact: QLabel(text(f"detail.{fact}")) for fact in _FACTS}
        self.facts = {fact: Note(self) for fact in _FACTS}
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        for row, fact in enumerate(_FACTS):
            self.labels[fact].setProperty("role", "secondary")
            grid.addWidget(self.labels[fact], row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(self.facts[fact], row, 1)
        grid.setColumnStretch(1, 1)
        self.why_title = QLabel(text("detail.why"))
        self.why_title.setProperty("role", "caption")
        self.why = Note(self)
        self.explain = ExplainPanel(window)

        inside = vbox(self.content, spacing=8)
        inside.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignLeft)
        inside.addWidget(self.name)
        inside.addWidget(self.folder)
        inside.addSpacing(8)
        inside.addLayout(grid)
        inside.addSpacing(8)
        inside.addWidget(divider())
        inside.addSpacing(8)
        inside.addWidget(self.why_title)
        inside.addWidget(self.why)
        inside.addSpacing(8)
        inside.addWidget(self.explain)
        layout = vbox(self, margins=(20, 32, 20, 24), spacing=0)
        layout.addWidget(self.none)
        layout.addWidget(self.content)
        layout.addStretch(1)
        self.show_finding(None, [])

    def show_finding(self, finding: Finding | None, roots: list[Path]) -> None:
        """``finding`` and the scanned folder it was found in among ``roots``; or none."""
        self.none.setHidden(finding is not None)
        self.content.setHidden(finding is None)
        self.explain.show_for(finding)
        if finding is None:
            return
        translator = self._window.translator
        entry = finding.entry
        path = Path(entry.path)
        home = Path.home()
        self.badge.setText(translator.label(finding.level))
        self.badge.setProperty("badge", finding.level.value)
        style = self.badge.style()
        style.unpolish(self.badge)
        style.polish(self.badge)
        self.name.setText(path.name)
        self.folder.setText(shown_path(path.parent, home))
        self.facts["size"].setText(translator.size(entry.size))
        self.facts["modified"].setText(moment(entry.mtime_ns / 1e9))
        self.facts["found"].setText(shown_path(found_in(path, roots), home))
        lines = [translator.reason(reason.evidence, reason.detail) for reason in finding.reasons]
        if finding.keeps is not None:
            lines.append(translator.text("detail.kept"))
        self.why.setText("\n".join(lines))


class FindingsPage(QWidget):
    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        self._findings: dict[str, Finding] = {}  # by path, in the analysis' order
        self._items: dict[str, QTreeWidgetItem] = {}
        self._roots: list[Path] = []
        self._syncing = False  # the page itself sets check states: no reaction to them
        translator = window.translator
        text = translator.text

        look = window.look
        self.rescan_button = button(look, text("findings.rescan"), icon="refresh-cw")
        self.rescan_button.clicked.connect(lambda _=False: window.overview.start_scan())
        window.add_starter(self.rescan_button)
        self.head = Head(text("page.findings"), text("head.findings"), self.rescan_button)
        self.filters = {
            level: chip(look, translator.label(level), checkable=True) for level in Level
        }
        for box in self.filters.values():
            box.setChecked(True)
            box.toggled.connect(self._filter)
        self.search = Field(look, text("findings.search"), "search")
        self.search.setMinimumWidth(SEARCH_WIDTHS[0])
        self.search.setMaximumWidth(SEARCH_WIDTHS[1])
        self.search.textChanged.connect(self._filter)
        self.tree = QTreeWidget()
        rows(self.tree, look)
        self.tree.setAccessibleName(text("findings.tree"))
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([text(f"findings.{name}") for name in ("name", "size", "level")])
        header = self.tree.headerItem()
        header.setTextAlignment(_SIZE, _RIGHT)
        self.tree.itemChanged.connect(self._changed)
        self.tree.currentItemChanged.connect(self._current)
        self.detail = FindingDetail(window)
        self.explain = self.detail.explain
        self.result = Note(self)
        self.chosen = QLabel()
        self.chosen.setProperty("role", "strong")
        self.chosen_size = QLabel()
        self.chosen_size.setProperty("role", "secondary")
        self.select_buttons = {
            level: link(text("findings.select", level=translator.label(level)))
            for level in _SELECTABLE
        }
        for level, chosen in self.select_buttons.items():
            chosen.clicked.connect(lambda _=False, level=level: self._select(level))
        self.clear_button = link(text("findings.clear"))
        self.clear_button.clicked.connect(self._clear)
        self.move_button = button(look, text("findings.move_ask"), role="primary")
        self.move_button.clicked.connect(self._move)

        filters = hbox(spacing=8)
        for box in self.filters.values():
            filters.addWidget(box)
        filters.addStretch(1)
        filters.addWidget(self.search, 4)  # as wide as it may be before the stretch grows
        amount = hbox(spacing=4)
        amount.addWidget(self.chosen)
        amount.addWidget(self.chosen_size)
        amount.addStretch(1)
        links = hbox(spacing=16)
        for chosen in self.select_buttons.values():
            links.addWidget(chosen)
        links.addWidget(self.clear_button)
        links.addStretch(1)
        inside_bar = QGridLayout()
        inside_bar.setContentsMargins(0, 0, 0, 0)
        inside_bar.setHorizontalSpacing(16)
        inside_bar.setVerticalSpacing(4)
        inside_bar.addLayout(amount, 0, 0)
        inside_bar.addWidget(self.move_button, 0, 1)
        inside_bar.addLayout(links, 1, 0, 1, 2)
        inside_bar.setColumnStretch(0, 1)
        self.bar, selection = bar()
        selection.addLayout(inside_bar, 1)
        main = QWidget()
        column = vbox(main, spacing=0)
        inside = vbox(margins=(32, 32, 32, 16), spacing=16)
        inside.addWidget(self.head)
        inside.addLayout(filters)
        inside.addWidget(self.tree, 1)
        inside.addWidget(self.result)
        column.addLayout(inside, 1)
        column.addWidget(self.bar)
        layout = hbox(self, spacing=0)
        layout.addWidget(main, 1)
        layout.addWidget(self.detail)
        window.add_starter(self.move_button, lambda: bool(self.selected()))
        self._refresh()

    # --- what is listed ------------------------------------------------------------------------

    def show_analysis(self, analysis: AnalysisReport, roots: list[Path], at: float) -> None:
        """List the findings of a new analysis of ``roots``, made at ``at``: what it proposes
        at the Safe level selected."""
        translator = self._window.translator
        self._roots = list(roots)
        self.head.subtitle.setText(
            translator.text(
                "findings.scan_of", folders=folders(translator, self._roots), moment=moment(at)
            )
        )
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
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_NAME, header.ResizeMode.Stretch)
        for column in (_SIZE, _LEVEL):
            self.tree.resizeColumnToContents(column)
        self.result.clear()
        self._filter()
        self._refresh()
        self._window.sidebar.set_count("findings", len(self._findings))

    def _add_group(self, evidence: Evidence, found: list[Finding]) -> None:
        translator = self._window.translator
        level = found[0].level
        group = QTreeWidgetItem(self.tree)
        group.setData(_NAME, _EVIDENCE, evidence.value)
        group.setText(_NAME, translator.label(evidence))
        group.setData(_NAME, EMPHASIS, True)
        group.setData(_SIZE, EMPHASIS, True)
        group.setTextAlignment(_SIZE, _RIGHT)
        group.setText(_LEVEL, translator.label(level))
        group.setData(_LEVEL, BADGE, level.value)
        group.setCheckState(_NAME, _UNCHECKED)
        home = Path.home()
        for finding in found:
            path = Path(finding.entry.path)
            item = QTreeWidgetItem(group, [path.name, translator.size(finding.entry.size)])
            item.setData(_NAME, SECONDARY, shown_path(path.parent, home))
            item.setData(_NAME, PATH, str(path))
            item.setData(_SIZE, QUIET, True)
            item.setTextAlignment(_SIZE, _RIGHT)
            if finding.keeps is None:
                preselected = finding.proposed and finding.level is Level.SAFE
                item.setCheckState(_NAME, _CHECKED if preselected else _UNCHECKED)
            else:  # the copy that stays: never moved, so never selected
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self._items[str(path)] = item

    def show_only(self, level: Level) -> None:
        """Only the findings of ``level``, and no search (item 48)."""
        self.search.clear()
        for shown, box in self.filters.items():
            box.setChecked(shown is level)

    def item(self, path: Path) -> QTreeWidgetItem:
        return self._items[str(path)]

    def findings(self) -> tuple[Finding, ...]:
        return tuple(self._findings.values())

    def selected(self) -> list[Finding]:
        """The findings checked, in the analysis' order."""
        return [
            finding
            for key, finding in self._findings.items()
            if self._items[key].checkState(_NAME) == _CHECKED
        ]

    def _groups(self) -> list[QTreeWidgetItem]:
        return _children(self.tree.invisibleRootItem())

    def _finding(self, item: QTreeWidgetItem) -> Finding:
        return self._findings[item.data(_NAME, PATH)]

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
        key = "" if current is None else current.data(_NAME, PATH)  # a group's: None
        self.detail.show_finding(self._findings.get(key), self._roots)

    # --- the selection -------------------------------------------------------------------------

    def _proposals_shown(self, items: list[QTreeWidgetItem]) -> list[QTreeWidgetItem]:
        return [item for item in items if self._finding(item).proposed and not item.isHidden()]

    def _checkable(self, items: list[QTreeWidgetItem]) -> list[QTreeWidgetItem]:
        return [item for item in items if self._finding(item).keeps is None]

    def _set(self, items: list[QTreeWidgetItem], state: Qt.CheckState) -> None:
        self._syncing = True
        for item in items:
            item.setCheckState(_NAME, state)
        self._syncing = False

    def _changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._syncing:
            return
        if item.parent() is None:  # a group: what it proposes and shows, or nothing of it
            children = _children(item)
            if item.checkState(_NAME) == _CHECKED:
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
        """Each group's files, rules, size and check state; each level's count; the
        selection's files and size."""
        translator = self._window.translator
        self._syncing = True
        for group in self._groups():
            children = _children(group)
            found = [self._finding(child) for child in children]
            group.setData(
                _NAME, SECONDARY, self._about(Evidence(group.data(_NAME, _EVIDENCE)), found)
            )
            group.setText(_SIZE, translator.size(sum(f.entry.size for f in found)))
            checkable = self._checkable(children)
            checked = sum(1 for child in checkable if child.checkState(_NAME) == _CHECKED)
            whole = _CHECKED if checked == len(checkable) else Qt.CheckState.PartiallyChecked
            group.setCheckState(_NAME, _UNCHECKED if checked == 0 else whole)
        self._syncing = False
        for level, box in self.filters.items():
            n = sum(1 for finding in self._findings.values() if finding.level is level)
            box.setText(translator.text("findings.chip", level=translator.label(level), n=n))
        chosen = self.selected()
        self.chosen.setText(
            translator.text("selected.files", files=translator.count("file", len(chosen)))
        )
        size = translator.size(sum(finding.entry.size for finding in chosen))
        self.chosen_size.setText(translator.text("selected.size", size=size))
        self._window.update_starters()

    def _about(self, evidence: Evidence, found: list[Finding]) -> str:
        """Under a group's reason: its files and, for junk, its rules; for duplicate copies,
        that one copy of each stays."""
        translator = self._window.translator
        files = translator.count("file", len(found))
        if evidence is Evidence.DUPLICATE_COPY:
            return translator.text("findings.copies", files=files)
        rules = dict.fromkeys(f.reasons[0].detail for f in found if evidence in _JUNK)
        if not rules:
            return files
        return translator.text("findings.rules", files=files, rules=", ".join(rules))

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
                if child.data(_NAME, PATH) in gone:
                    group.removeChild(child)
            if group.childCount() == 0:
                root.removeChild(group)
        for key in gone:
            del self._findings[key]
            del self._items[key]
        self._window.sidebar.set_count("findings", len(self._findings))
