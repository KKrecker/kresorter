"""The Organize page: a folder's plan, its batch carried out after confirmation, the batches and
their undo (decision 0014, items 14 and 23).

Where organize does not move files (0012 item 37: not Linux, or no reliable open-file check),
the page says why and offers nothing else, and reads no journal. Elsewhere each step is a
session of its own (``ui.sessions``), as ``organize move``, ``list`` and ``undo`` run them: a
folder's plan shows the moves by category and the files that stay, with their reasons; after
confirmation the plan is made again inside the session and only the confirmed moves it still
holds unchanged are carried out, as one batch, which the result names, with what changed since
the plan, what was refused at move time and, when the batch stopped, its state and what is still
sorted. Every session ends with the batches as they are then, newest first; they are read again
each time the page opens. Undo shows the undo's plan first and, confirmed, moves back only what
its plan, made again, still holds.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from safeclean.organize.folders import FolderRefused
from safeclean.organize.journal import Batch, BatchState, Summary
from safeclean.organize.mover import BatchResult, Planned
from safeclean.organize.planner import Move, Plan, Stay
from safeclean.organize.platforms import blockers
from safeclean.organize.undo import UndoPlan, UndoRefused
from safeclean.storage.pending import Domain
from safeclean.storage.session import SessionFailed
from safeclean.ui.dialogs import Confirmation
from safeclean.ui.recovery import organize_lines
from safeclean.ui.sessions import (
    Act,
    Carried,
    Organized,
    Unfinished,
    in_organize,
    no_act,
    plan_folder,
    sort_folder,
    undo_batch,
    undo_plan,
)
from safeclean.ui.tasks import Task

if TYPE_CHECKING:
    from safeclean.ui.window import Window

__all__ = ["OrganizePage"]

T = TypeVar("T")
_NO_PLAN = Plan(Path(), (), ())
_COLUMNS = ("id", "time", "kind", "moved", "state", "folder")


def _label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _moment(created_at_ns: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at_ns / 1e9))


class OrganizePage(QWidget):
    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        self._plan = _NO_PLAN
        self._rows: dict[int, QTreeWidgetItem] = {}
        translator = window.translator
        text = translator.text
        context = window.environment.scan_context()
        found = blockers(context.platform, context.open_files)
        self._blocked = bool(found)

        heading = QLabel(text("page.organize"))
        heading.setProperty("role", "heading")
        why = [translator.label(blocker) for blocker in found]
        self.blocked = _label("\n".join([text("organize.blocked"), *why]))
        self.blocked.setHidden(not found)
        self.controls = QWidget()
        self.controls.setHidden(self._blocked)

        self.choose_button = QPushButton(text("organize.choose"))
        self.choose_button.clicked.connect(self._choose)
        self.summary = _label()
        self.plan = QTreeWidget()
        self.plan.setAccessibleName(text("organize.plan"))
        self.plan.setHeaderHidden(True)
        self.move_button = QPushButton(text("organize.move"))
        self.move_button.setProperty("role", "primary")
        self.move_button.clicked.connect(self._move)
        self.batches = QTreeWidget()
        self.batches.setAccessibleName(text("batches.title"))
        self.batches.setRootIsDecorated(False)
        self.batches.setColumnCount(len(_COLUMNS))
        self.batches.setHeaderLabels([text(f"batches.{name}") for name in _COLUMNS])
        self.batches.itemSelectionChanged.connect(window.update_starters)
        self.undo_button = QPushButton(text("organize.undo"))
        self.undo_button.clicked.connect(self._undo)
        self.result = _label()

        choose = QHBoxLayout()
        choose.addWidget(self.choose_button)
        choose.addStretch(1)
        move = QHBoxLayout()
        move.addStretch(1)
        move.addWidget(self.move_button)
        undo = QHBoxLayout()
        undo.addStretch(1)
        undo.addWidget(self.undo_button)
        batches = QLabel(text("batches.title"))
        inside = QVBoxLayout(self.controls)
        inside.setContentsMargins(0, 0, 0, 0)
        inside.addLayout(choose)
        inside.addWidget(self.summary)
        inside.addWidget(self.plan, 1)
        inside.addLayout(move)
        inside.addWidget(batches)
        inside.addWidget(self.batches, 1)
        inside.addLayout(undo)
        inside.addWidget(self.result)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(self.blocked)
        layout.addWidget(self.controls, 1)
        layout.addStretch(0)
        window.add_starter(self.choose_button)
        window.add_starter(self.move_button, lambda: bool(self._plan.moves))
        window.add_starter(self.undo_button, lambda: bool(self.batches.selectedItems()))

    def batch_row(self, batch_id: int) -> QTreeWidgetItem:
        return self._rows[batch_id]

    # --- sessions ------------------------------------------------------------------------------

    def load(self) -> None:
        """Read the batches again; nothing where organize does not move files."""
        if self._blocked:
            return
        self._session("task.batches", no_act, lambda _: self.result.clear(), listing=True)

    def _session(
        self, title: str, act: Act[T], show: Callable[[T], None], *, listing: bool = False
    ) -> None:
        window = self._window
        environment = window.environment

        def work() -> Organized[T] | Unfinished | SessionFailed:
            return in_organize(environment.scan_context(), act, listing=listing)

        def done(outcome: Organized[T] | Unfinished | SessionFailed) -> None:
            if not isinstance(outcome, Organized):
                self.result.setText(window.refusal(outcome))
                return
            window.recovery.report(
                Domain.ORGANIZE, organize_lines(window.translator, outcome.recovered)
            )
            show(outcome.result)
            self._list(outcome.batches)

        window.run(Task(window.translator.text(title), work, done, acts=True))

    def _list(self, batches: Sequence[Summary]) -> None:
        self.batches.clear()
        self._rows = {}
        for summary in batches:
            batch = summary.batch
            cells = [
                str(batch.batch_id),
                _moment(batch.created_at_ns),
                self._kind(batch),
                str(summary.moved),
                self._state(summary),
                str(batch.folder),
            ]
            self._rows[batch.batch_id] = QTreeWidgetItem(self.batches, cells)
        for column in range(self.batches.columnCount()):
            self.batches.resizeColumnToContents(column)
        self._window.update_starters()

    def _kind(self, batch: Batch) -> str:
        translator = self._window.translator
        kind = translator.label(batch.kind)
        undoing = batch.undoing
        return (
            kind
            if undoing is None
            else translator.text("batches.undo_of", kind=kind, batch=undoing)
        )

    def _state(self, summary: Summary) -> str:
        translator = self._window.translator
        state = translator.label(summary.batch.state)
        if not summary.undone:
            return state
        key = "batches.undone" if summary.undone == summary.moved else "batches.partly_undone"
        return translator.text(key, state=state)

    # --- the plan and its batch ----------------------------------------------------------------

    def _choose(self) -> None:
        folder = self._window.dialogs.choose_folder()
        if folder is None:
            return
        self._session("task.plan", plan_folder(folder), self._planned)

    def _planned(self, found: Plan | FolderRefused) -> None:
        translator = self._window.translator
        self.plan.clear()
        self.result.clear()
        self._plan = _NO_PLAN
        if isinstance(found, FolderRefused):
            self.summary.setText(self._refused(found))
            return
        self._plan = found
        amount = self._amount(found.moves)
        key = "organize.would" if found.moves else "organize.nothing"
        self.summary.setText(translator.text(key, folder=found.folder, **amount))
        groups: dict[str, list[Move]] = {}
        for move in found.moves:
            groups.setdefault(move.category, []).append(move)
        for category, moves in groups.items():
            title = translator.text("organize.category", category=category, **self._amount(moves))
            self._group(title, [self._line(move) for move in moves])
        if found.stays:
            title = translator.text("organize.stays", n=len(found.stays))
            self._group(title, self._stays(found.stays, found.folder))
        self.plan.expandAll()

    def _group(self, title: str, lines: Sequence[str]) -> None:
        group = QTreeWidgetItem(self.plan, [title])
        for line in lines:
            QTreeWidgetItem(group, [line])

    def _move(self) -> None:
        translator = self._window.translator
        found = self._plan
        action = translator.text("organize.move")
        asked = Confirmation(
            title=action,
            text=translator.text(
                "organize.confirm", folder=found.folder, **self._amount(found.moves)
            ),
            details=tuple(self._line(move) for move in found.moves),
            action=action,
        )
        if not self._window.dialogs.confirm(asked):
            return
        self._session("task.organize", sort_folder(found.folder, found.moves), self._sorted)

    def _sorted(self, carried: Carried | FolderRefused) -> None:
        text = self._window.translator.text
        self._plan = _NO_PLAN
        self.plan.clear()
        self.summary.clear()
        if isinstance(carried, FolderRefused):
            self.result.setText(self._refused(carried))
            return
        folder = carried.folder

        def done(batch: BatchResult) -> str:
            amount = self._amount(carried.moved)
            return text("organize.done", folder=folder, batch=batch.batch_id, **amount)

        def stopped(batch: BatchResult) -> list[str]:
            still = [text("organize.still", path=path) for path in batch.left]
            return still + ([text("organize.left", batch=batch.batch_id)] if still else [])

        self._report(carried, text("organize.nothing_moved", folder=folder), done, stopped)

    # --- undo ----------------------------------------------------------------------------------

    def _undo(self) -> None:
        [row] = self.batches.selectedItems()  # enabled with one batch selected, the most there is
        batch_id = int(row.text(0))
        self._session("task.plan_undo", undo_plan(batch_id), self._undo_planned)

    def _undo_planned(self, found: UndoPlan | UndoRefused) -> None:
        translator = self._window.translator
        text = translator.text
        if isinstance(found, UndoRefused):
            reason = translator.label(found.reason)
            self.result.setText(text("undo.refused", batch=found.batch_id, reason=reason))
            return
        batch_id, folder = found.batch_id, found.folder
        stays = self._stays(found.stays, folder)
        if not found.moves:
            self.result.setText("\n".join([text("undo.nothing", batch=batch_id), *stays]))
            return
        back = [
            text(
                "undo.line",
                source=move.source.relative_to(folder),
                destination=move.destination.relative_to(folder),
            )
            for move in found.moves
        ]
        asked = Confirmation(
            title=text("undo.title", batch=batch_id),
            text=text("undo.confirm", batch=batch_id, folder=folder, **self._amount(found.moves)),
            details=(*back, *stays),
            action=text("undo.action"),
        )
        if not self._window.dialogs.confirm(asked):
            return
        act = undo_batch(batch_id, found.moves)
        self._session("task.undo", act, lambda carried: self._undone(carried, batch_id))

    def _undone(self, carried: Carried, undoing: int) -> None:
        text = self._window.translator.text

        def done(batch: BatchResult) -> str:
            amount = self._amount(carried.moved)
            return text(
                "undo.done", folder=carried.folder, batch=batch.batch_id, undoing=undoing, **amount
            )

        def stopped(batch: BatchResult) -> list[str]:
            return [text("undo.again", batch=undoing)]

        self._report(carried, text("undo.nothing_moved", batch=undoing), done, stopped)

    # --- what the results say ------------------------------------------------------------------

    def _report(
        self,
        carried: Carried,
        nothing: str,
        done: Callable[[BatchResult], str],
        stopped: Callable[[BatchResult], list[str]],
    ) -> None:
        """What a confirmed batch came to: ``nothing`` when nothing was carried out; ``done``,
        or the stop and ``stopped``; then what was refused and what changed since the plan."""
        translator = self._window.translator
        batch = carried.batch
        if batch is None:
            lines = [nothing]
        elif batch.state is BatchState.DONE:
            lines = [done(batch)]
        else:
            state = translator.label(batch.state)
            head = translator.text(
                "organize.stopped", error=batch.error, batch=batch.batch_id, state=state
            )
            lines = [head, *stopped(batch)]
        lines += [
            translator.text(
                "move.refused",
                path=refusal.path,
                reason=translator.reason(refusal.reason, refusal.detail),
            )
            for refusal in carried.refused
        ]
        lines += [translator.text("organize.changed", path=path) for path in carried.changed]
        self.result.setText("\n".join(lines))

    def _refused(self, refused: FolderRefused) -> str:
        translator = self._window.translator
        reason = translator.reason(refused.reason, refused.detail)
        return translator.text("organize.refused", folder=refused.folder, reason=reason)

    def _amount(self, moves: Sequence[Planned]) -> dict[str, str]:
        translator = self._window.translator
        files = translator.count("file", len(moves))
        return {"files": files, "size": translator.size(sum(move.size for move in moves))}

    def _line(self, move: Move) -> str:
        text = self._window.translator.text
        return text("organize.line", name=move.source.name, category=move.category)

    def _stays(self, stays: Sequence[Stay], folder: Path) -> list[str]:
        translator = self._window.translator
        return [
            translator.text(
                "organize.stay",
                name=stay.path.relative_to(folder),
                reason=translator.reason(stay.reason, stay.detail),
            )
            for stay in stays
        ]
