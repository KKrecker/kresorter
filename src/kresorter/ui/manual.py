"""Editable, in-memory assignments for the manual file organizer."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QIcon
from PySide6.QtWidgets import QAbstractItemView, QDialog, QLineEdit, QListWidget, QListWidgetItem

from kresorter.llm.group import Grouping, group, names_to_group
from kresorter.organize.names import fold, is_folder_name
from kresorter.organize.planner import Plan, StayReason
from kresorter.ui import icons
from kresorter.ui.parts import Label, Note, button, hbox, tooltip, vbox
from kresorter.ui.tasks import Task

if TYPE_CHECKING:
    from kresorter.ui.window import Window


class GroupTiles(QListWidget):
    """Accept only an internal drag of selected file tiles onto a group tile."""

    def __init__(self, files: QListWidget, assign: Callable[[], None]) -> None:
        super().__init__()
        self.files = files
        self.assign = assign
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.source() is self.files:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.source() is self.files and self.itemAt(event.position().toPoint()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        if event.source() is not self.files or item is None:
            event.ignore()
            return
        self.setCurrentItem(item)
        self.assign()
        event.acceptProposedAction()


class ManualDialog(QDialog):
    """Stage assignments without touching the disk; the page previews the accepted plan."""

    def __init__(self, window: Window, plan: Plan, initial: Mapping[str, str]) -> None:
        super().__init__(window)
        self.setWindowTitle(window.translator.text("manual.title"))
        self.resize(880, 580)
        self.assignments: dict[str, str] = {}
        self._window = window
        self._plan = plan
        self._thinking = False
        window.tasks.busy.connect(self._busy_changed)
        text = window.translator.text
        look = window.look
        self.group_name = QLineEdit()
        self.group_name.setPlaceholderText(text("manual.group_placeholder"))
        self.group_name.setAccessibleName(text("manual.group_placeholder"))
        self.add_group = button(look, text("manual.add_group"), icon="plus")
        self.add_group.clicked.connect(self._add_group)
        self.message = Note(self)
        self.files = QListWidget()
        self.files.setAccessibleName(text("manual.files"))
        self.files.setProperty("role", "manual-tiles")
        self.files.setViewMode(QListWidget.ViewMode.IconMode)
        self.files.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.files.setMovement(QListWidget.Movement.Static)
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.setGridSize(QSize(150, 82))
        self.files.setIconSize(QSize(24, 24))
        self.files.setDragEnabled(True)
        self.files.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.groups = GroupTiles(self.files, self._assign)
        self.groups.setAccessibleName(text("manual.groups"))
        self.groups.setProperty("role", "manual-tiles")
        self.groups.setViewMode(QListWidget.ViewMode.IconMode)
        self.groups.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.groups.setMovement(QListWidget.Movement.Static)
        self.groups.setGridSize(QSize(150, 82))
        self.groups.setIconSize(QSize(24, 24))
        file_icon = QIcon(icons.pixmap("file-text", look.palette.text, 24))
        names = {move.source.name for move in plan.moves}
        names.update(
            s.path.name
            for s in plan.stays
            if s.reason in {StayReason.UNKNOWN_KIND, StayReason.COMPANION}
        )
        for name in sorted(names):
            item = QListWidgetItem(file_icon, name, self.files)
            item.setData(Qt.ItemDataRole.UserRole, name)
        self.assign = button(look, text("manual.assign"))
        self.assign.clicked.connect(self._assign)
        self.clear = button(look, text("manual.clear"))
        self.clear.clicked.connect(self._clear)
        self.search = QLineEdit()
        self.search.setPlaceholderText(text("manual.search"))
        self.search.setAccessibleName(text("manual.search"))
        self.search.textChanged.connect(self._filter)
        self.ai = button(look, text("manual.ai"), icon="sparkles")
        self.ai.setEnabled(len(names_to_group(plan)) >= 2)
        self.ai.clicked.connect(self._suggest)
        self.cancel = button(look, text("button.cancel"))
        self.cancel.clicked.connect(self.reject)
        self.preview = button(look, text("manual.preview"), role="primary")
        self.preview.clicked.connect(self.accept)
        self.preview.setEnabled(False)
        self.files.itemSelectionChanged.connect(self._buttons)
        self.groups.itemSelectionChanged.connect(self._buttons)
        top = hbox(spacing=8)
        top.addWidget(self.group_name, 1)
        top.addWidget(self.add_group)
        columns = hbox(spacing=16)
        left = vbox(spacing=8)
        left.addWidget(Label(text("manual.files")))
        left.addWidget(self.search)
        left.addWidget(self.files, 1)
        right = vbox(spacing=8)
        right.addWidget(Label(text("manual.groups")))
        right.addLayout(top)
        right.addWidget(self.groups, 1)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        actions = hbox(spacing=8)
        actions.addWidget(self.assign)
        actions.addWidget(self.clear)
        actions.addStretch(1)
        actions.addWidget(self.ai)
        finish = hbox(spacing=8)
        finish.addStretch(1)
        finish.addWidget(self.cancel)
        finish.addWidget(self.preview)
        layout = vbox(self, margins=(24, 24, 24, 24), spacing=16)
        layout.addWidget(Label(text("manual.hint")))
        layout.addWidget(Label(text("manual.limitation")))
        layout.addWidget(Label(text("manual.privacy")))
        layout.addLayout(columns, 1)
        layout.addWidget(self.message)
        layout.addLayout(actions)
        layout.addLayout(finish)
        for name, category in initial.items():
            if name in names:
                self.assignments[name] = self._ensure_group(category)
        self._refresh()

    def _ensure_group(self, name: str) -> str:
        for index in range(self.groups.count()):
            item = self.groups.item(index)
            if fold(item.text()) == fold(name):
                self.groups.setCurrentItem(item)
                return item.text()
        icon = QIcon(icons.pixmap("folder", self._window.look.palette.text, 24))
        self.groups.setCurrentItem(QListWidgetItem(icon, name, self.groups))
        return name

    def _add_group(self) -> None:
        name = self.group_name.text().strip()
        if not is_folder_name(name):
            self.message.setText(self._window.translator.text("manual.invalid_group"))
            return
        self.message.clear()
        self._ensure_group(name)
        self.group_name.clear()
        self._buttons()

    def _filter(self, query: str) -> None:
        for index in range(self.files.count()):
            item = self.files.item(index)
            hidden = fold(query) not in fold(str(item.data(Qt.ItemDataRole.UserRole)))
            if hidden:
                item.setSelected(False)
            item.setHidden(hidden)

    def _suggest(self) -> None:
        window = self._window
        env, language = window.llm_env, window.translator.language
        limits = window.environment.llm_limits
        self._thinking = True
        self.ai.setEnabled(False)
        self.preview.setEnabled(False)

        def work() -> Grouping:
            return group(self._plan, env, language, limits=limits)

        def done(found: Grouping) -> None:
            self._thinking = False
            if not self.isVisible():
                return
            self.ai.setEnabled(True)
            if found.unavailable is not None and not found.groups:
                reason = window.translator.reason(
                    found.unavailable.reason, found.unavailable.detail
                )
                self.message.setText(window.translator.text("manual.ai_failed", reason=reason))
            elif not found.groups:
                self.message.setText(window.translator.text("manual.ai_empty"))
            else:
                names = {
                    str(self.files.item(i).data(Qt.ItemDataRole.UserRole))
                    for i in range(self.files.count())
                }
                for name, proposed in found.groups.items():
                    if name in names and name not in self.assignments:
                        self.assignments[name] = self._ensure_group(proposed)
                if found.unavailable is None:
                    self.message.setText(window.translator.text("manual.ai_done"))
                else:
                    reason = window.translator.reason(
                        found.unavailable.reason, found.unavailable.detail
                    )
                    self.message.setText(window.translator.text("manual.ai_partial", reason=reason))
            self._refresh()

        if not window.run(Task(window.translator.text("task.group"), work, done)):
            self._thinking = False
            self.ai.setEnabled(True)
            self._buttons()

    def _busy_changed(self, busy: bool) -> None:
        if not busy and self._thinking:
            self._thinking = False
            self.ai.setEnabled(True)
            self.message.setText(self._window.translator.text("manual.ai_error"))
            self._buttons()

    def _assign(self) -> None:
        item = self.groups.currentItem()
        if item is None:
            return
        for selected in self.files.selectedItems():
            self.assignments[str(selected.data(Qt.ItemDataRole.UserRole))] = item.text()
        self._refresh()

    def _clear(self) -> None:
        for selected in self.files.selectedItems():
            self.assignments.pop(str(selected.data(Qt.ItemDataRole.UserRole)), None)
        self._refresh()

    def _refresh(self) -> None:
        for index in range(self.files.count()):
            item = self.files.item(index)
            name = str(item.data(Qt.ItemDataRole.UserRole))
            group = self.assignments.get(name)
            item.setText(name if group is None else f"{name}\n→ {group}")
            item.setToolTip(tooltip(name if group is None else f"{name} → {group}"))
        self._buttons()

    def _buttons(self) -> None:
        selected = bool(self.files.selectedItems())
        self.assign.setEnabled(selected and self.groups.currentItem() is not None)
        self.clear.setEnabled(selected)
        self.preview.setEnabled(bool(self.assignments) and not self._thinking)
