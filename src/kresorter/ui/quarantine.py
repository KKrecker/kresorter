"""The Quarantine page: the files in the quarantine, Restore and Delete permanently (decision
0014, items 5, 22 and 51).

A row per file: its name and under it its original folder, its size and its id; with no file,
that the quarantine is empty. The bar at the bottom says how many files are checked and their
size, beside Restore and Delete permanently. The list is read from the journal each time the
page opens, and on Refresh, in a session of its own (``ui.sessions``), as ``quarantine list``
reads it; every session ends with the list as it is then. Restore and Delete permanently act on
the files checked, after a confirmation: a deletion's plan, with its total size, is made first
and shown in the dialog, and the deletion plans again inside its own session, so that only the
confirmed files the plan still holds are deleted (item 14). Delete permanently is the one action
drawn in the danger colour.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QWidget

from kresorter.quarantine.journal import QuarantinedItem
from kresorter.quarantine.service import (
    PurgePlan,
    PurgeRefused,
    PurgeResult,
    QuarantineService,
    RestoreRefused,
    RestoreResult,
)
from kresorter.storage.pending import Domain
from kresorter.storage.session import SessionFailed
from kresorter.ui.dialogs import Confirmation
from kresorter.ui.parts import QUIET, SECONDARY, Head, Note, badge, bar, button, hbox, rows, vbox
from kresorter.ui.recovery import quarantine_lines
from kresorter.ui.sessions import Done, NoReliableCheck, Unfinished, in_quarantine
from kresorter.ui.shown import shown_path
from kresorter.ui.tasks import Task

if TYPE_CHECKING:
    from kresorter.ui.window import Window

__all__ = ["QuarantinePage"]

T = TypeVar("T")
_CHECKED, _UNCHECKED = Qt.CheckState.Checked, Qt.CheckState.Unchecked
_NAME, _SIZE, _ID = range(3)  # the columns
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class QuarantinePage(QWidget):
    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        self._listed: dict[int, QuarantinedItem] = {}
        self._rows: dict[int, QTreeWidgetItem] = {}
        text = window.translator.text

        look = window.look
        self.items = QTreeWidget()
        rows(self.items, look)
        self.items.setAccessibleName(text("quarantine.items"))
        self.items.setRootIsDecorated(False)
        self.items.setColumnCount(3)
        self.items.setHeaderLabels([text(f"quarantine.{name}") for name in ("name", "size", "id")])
        self.items.headerItem().setTextAlignment(_SIZE, _RIGHT)
        self.items.itemChanged.connect(self._chosen)
        self.empty = Note(self, role="secondary")
        self.total = Note(self, role="secondary")
        self.refresh_button = button(look, text("quarantine.refresh"), icon="refresh-cw")
        self.refresh_button.clicked.connect(self.load)
        self.restore_button = button(look, text("quarantine.restore"), role="primary")
        self.restore_button.clicked.connect(self._restore)
        self.purge_button = button(look, text("quarantine.purge"), role="danger")
        self.purge_button.clicked.connect(self._purge)
        self.permanent = badge(text("quarantine.permanent"), "danger")
        self.result = Note(self)
        self.chosen = QLabel()
        self.chosen.setProperty("role", "strong")
        self.chosen_size = QLabel()
        self.chosen_size.setProperty("role", "secondary")

        amount = hbox(spacing=4)
        amount.addWidget(self.chosen)
        amount.addWidget(self.chosen_size)
        self.bar, buttons = bar()
        buttons.addLayout(amount)
        buttons.addStretch(1)
        buttons.addWidget(self.restore_button)
        buttons.addWidget(self.permanent, 0, Qt.AlignmentFlag.AlignVCenter)
        buttons.addWidget(self.purge_button)
        self.head = Head(text("page.quarantine"), text("head.quarantine"), self.refresh_button)
        inside = vbox(margins=(32, 32, 32, 16), spacing=16)
        inside.addWidget(self.head)
        inside.addWidget(self.items, 1)
        inside.addWidget(self.empty)
        inside.addWidget(self.total)
        inside.addWidget(self.result)
        inside.addStretch(0)  # the room the list leaves, when there is none
        layout = vbox(self, spacing=0)
        layout.addLayout(inside, 1)
        layout.addWidget(self.bar)
        window.add_starter(self.refresh_button)
        window.add_starter(self.restore_button, lambda: bool(self.selected()))
        window.add_starter(self.purge_button, lambda: bool(self.selected()))
        self._chosen()

    def row(self, item_id: int) -> QTreeWidgetItem:
        return self._rows[item_id]

    def selected(self) -> list[int]:
        """The ids checked, in order."""
        return [item_id for item_id, row in self._rows.items() if row.checkState(_NAME) == _CHECKED]

    def _chosen(self) -> None:
        """The files checked, and their size."""
        translator = self._window.translator
        chosen = [self._listed[item_id] for item_id in self.selected()]
        files = translator.count("file", len(chosen))
        size = translator.size(sum(item.size for item in chosen))
        self.chosen.setText(translator.text("selected.files", files=files))
        self.chosen_size.setText(translator.text("selected.size", size=size))
        self._window.update_starters()

    # --- sessions ------------------------------------------------------------------------------

    def load(self) -> None:
        """Read the list again."""
        self._session("task.list", _nothing, lambda _: self.result.clear(), listing=True)

    def _session(
        self,
        title: str,
        act: Callable[[QuarantineService], T],
        show: Callable[[T], None],
        *,
        listing: bool = False,
    ) -> None:
        window = self._window
        environment = window.environment

        def work() -> Done[T] | Unfinished | NoReliableCheck | SessionFailed:
            return in_quarantine(environment.scan_context(), act, listing=listing)

        def done(outcome: Done[T] | Unfinished | NoReliableCheck | SessionFailed) -> None:
            if not isinstance(outcome, Done):
                self.result.setText(window.refusal(outcome, no_check="quarantine.no_check"))
                return
            window.recovery.report(
                Domain.QUARANTINE, quarantine_lines(window.translator, outcome.recovered)
            )
            show(outcome.result)
            self._list(outcome.listed)

        window.run(Task(window.translator.text(title), work, done, acts=True))

    def _list(self, listed: Sequence[QuarantinedItem]) -> None:
        """Show ``listed``, or that the quarantine is empty; what was checked and is still there
        stays checked."""
        translator = self._window.translator
        checked = set(self.selected())
        self.items.blockSignals(True)
        self.items.clear()
        self._listed = {item.item_id: item for item in listed}
        self._rows = {}
        home = Path.home()
        for item in listed:
            original = item.original
            size = translator.size(item.size)
            row = QTreeWidgetItem(self.items, [original.name, size, str(item.item_id)])
            row.setData(_NAME, SECONDARY, shown_path(original.parent, home))
            row.setTextAlignment(_SIZE, _RIGHT)
            for column in (_SIZE, _ID):
                row.setData(column, QUIET, True)
            row.setCheckState(_NAME, _CHECKED if item.item_id in checked else _UNCHECKED)
            self._rows[item.item_id] = row
        self.items.blockSignals(False)
        header = self.items.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_NAME, header.ResizeMode.Stretch)
        for column in (_SIZE, _ID):
            self.items.resizeColumnToContents(column)
        self.items.setHidden(not listed)
        self.empty.setText("" if listed else translator.text("quarantine.empty"))
        files = translator.count("file", len(listed))
        size = translator.size(sum(item.size for item in listed))
        total = translator.text("quarantine.total", files=files, size=size)
        self.total.setText(total if listed else "")
        self._window.sidebar.set_count("quarantine", len(listed))
        self._window.overview.show_quarantine((len(listed), sum(item.size for item in listed)))
        self._chosen()

    def _refusals(
        self, refused: Sequence[RestoreRefused | PurgeRefused], paths: Mapping[int, Path]
    ) -> list[str]:
        translator = self._window.translator
        return [
            translator.text(
                "item.refused",
                item=refusal.item_id,
                path=paths[refusal.item_id],
                reason=translator.reason(refusal.reason, refusal.detail),
            )
            for refusal in refused
        ]

    def _show(self, lines: list[str]) -> None:
        self.result.setText("\n".join(lines))

    # --- restore -------------------------------------------------------------------------------

    def _restore(self) -> None:
        translator = self._window.translator
        ids = self.selected()
        chosen = [self._listed[item_id] for item_id in ids]
        action = translator.text("quarantine.restore")
        files = translator.count("file", len(chosen))
        size = translator.size(sum(item.size for item in chosen))
        asked = Confirmation(
            title=action,
            text=translator.text("restore.confirm", files=files, size=size),
            details=tuple(str(item.original) for item in chosen),
            action=action,
        )
        if not self._window.dialogs.confirm(asked):
            return
        paths = {item.item_id: item.original for item in chosen}
        self._session(
            "task.restore", lambda service: service.restore(ids), lambda r: self._restored(r, paths)
        )

    def _restored(self, result: RestoreResult, paths: Mapping[int, Path]) -> None:
        files = self._window.translator.count("file", len(result.restored))
        done = self._window.translator.text("restore.done", files=files)
        self._show([done, *self._refusals(result.refused, paths)])

    # --- delete permanently --------------------------------------------------------------------

    def _purge(self) -> None:
        ids = self.selected()
        paths = {item_id: self._listed[item_id].original for item_id in ids}
        self._session(
            "task.plan_purge",
            lambda service: service.plan_purge(ids),
            lambda plan: self._planned(plan, paths),
        )

    def _planned(self, plan: PurgePlan, paths: Mapping[int, Path]) -> None:
        """The plan made: confirmed, it is made again, and carried out, in a session of its
        own."""
        translator = self._window.translator
        if not plan.items:
            self._show([translator.text("purge.nothing"), *self._refusals(plan.refused, paths)])
            return
        action = translator.text("quarantine.purge")
        files = translator.count("file", len(plan.items))
        asked = Confirmation(
            title=action,
            text=translator.text(
                "purge.confirm", files=files, size=translator.size(plan.total_bytes)
            ),
            details=tuple(str(item.original) for item in plan.items),
            action=action,
            danger=True,
        )
        if not self._window.dialogs.confirm(asked):
            return
        confirmed = [item.item_id for item in plan.items]
        self._session(
            "task.purge",
            lambda service: service.purge(service.plan_purge(confirmed)),
            lambda result: self._purged(result, paths),
        )

    def _purged(self, result: PurgeResult, paths: Mapping[int, Path]) -> None:
        translator = self._window.translator
        files = translator.count("file", len(result.purged))
        freed = translator.size(result.freed_bytes)
        done = translator.text("purge.done", files=files, size=freed)
        self._show([done, *self._refusals(result.refused, paths)])


def _nothing(service: QuarantineService) -> None:
    return None
