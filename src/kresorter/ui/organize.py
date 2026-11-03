"""The Organize page: a folder's plan, its batch carried out after confirmation, the batches and
their undo (decision 0014, items 14, 23, 26, 44 and 52).

Where organize does not move files (0012 item 37: not Linux, or no reliable open-file check), the
page says why and offers nothing else, and reads no journal. Elsewhere each step is a session of its
own (``ui.sessions``), as ``organize move``, ``list`` and ``undo`` run them. The folder is shown in
a field, from the home folder as ``~``, with Choose folder… or, once chosen, Change…, and the
plan's state at the right. A folder's plan shows a card per category of its moves (named in the
window's language, with the directory on disk beside it when that is named otherwise; every path
keeps the name on disk), three to a row, and the files that stay, with their reasons; the detail
of a file that stays has Explain (local AI) (``ui.explain``). The bar at the bottom says how many
files move into how many folders, beside Sort…: after confirmation the plan is made again inside
the session and only the confirmed moves it still holds unchanged are carried out, as one batch,
which the result names, with what changed since the plan, what was refused at move time and,
when the batch stopped, its state and what is still sorted. Every session ends with the batches
as they are then, newest first, in the card of the recent batches; they are read again each time
the page opens. Undo shows the undo's plan first and, confirmed, moves back only what its plan,
made again, still holds.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QFrame,
    QGridLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from kresorter.organize.folders import FolderRefused
from kresorter.organize.journal import Batch, BatchState, Summary
from kresorter.organize.mover import BatchResult, Planned
from kresorter.organize.planner import Move, Plan, Stay
from kresorter.organize.platforms import blockers
from kresorter.organize.undo import UndoPlan, UndoRefused
from kresorter.storage.pending import Domain
from kresorter.storage.session import SessionFailed
from kresorter.ui.dialogs import Confirmation
from kresorter.ui.explain import ExplainPanel
from kresorter.ui.parts import (
    QUIET,
    SECONDARY,
    Field,
    Head,
    Icon,
    Note,
    bar,
    button,
    card,
    hbox,
    rows,
    shares,
    surface2_tile,
    text_ink,
    vbox,
)
from kresorter.ui.recovery import organize_lines
from kresorter.ui.sessions import (
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
from kresorter.ui.shown import moment, shown_path
from kresorter.ui.tasks import Task

if TYPE_CHECKING:
    from kresorter.ui.i18n import Translator
    from kresorter.ui.theme import Look
    from kresorter.ui.window import Window

__all__ = ["BATCHES_WIDTH", "CATEGORY_ICONS", "PER_ROW", "CategoryCard", "OrganizePage"]

T = TypeVar("T")
_NO_PLAN = Plan(Path(), (), ())
_STAY = Qt.ItemDataRole.UserRole  # a file that stays keeps its place in the plan's stays
_BATCH = Qt.ItemDataRole.UserRole  # a batch's row keeps its id
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
PER_ROW = 3  # category cards to a row
BATCHES_WIDTH = 320  # px: the card of the recent batches, at the right
_NAMES = 3  # a category's card names its first three files
CATEGORY_ICONS = {
    "Images": "image",
    "Videos": "square-play",
    "Audio": "music",
    "Documents": "file-text",
    "Archives": "archive",
    "Installers": "download",
}  # a category the table names otherwise has the folder icon


def _fits(tree: QTreeWidget) -> None:
    """A list as high as its rows: the page scrolls, not the list."""
    tree.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
    tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    tree.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    tree.setHeaderHidden(True)
    tree.setRootIsDecorated(False)


class CategoryCard(QFrame):
    """A category of the plan: its icon, its files and their size, its name (item 44) and its
    first three file names."""

    def __init__(
        self, look: Look, translator: Translator, category: str, moves: Sequence[Move]
    ) -> None:
        super().__init__()
        self.setProperty("role", "card")
        shares(self)
        self.category = category
        icon = CATEGORY_ICONS.get(category, "folder")
        self.icon = Icon(look, icon, text_ink, size=18, tile=surface2_tile, side=32)
        files = translator.count("file", len(moves))
        size = translator.size(sum(move.size for move in moves))
        self.amount = QLabel(translator.text("organize.amount", files=files, size=size))
        self.amount.setProperty("role", "secondary")
        label = translator.category(category)
        named = translator.text("organize.named", label=label, category=category)
        self.name = QLabel(label if label == category else named)
        self.name.setProperty("role", "card-title")
        self.names = QLabel(", ".join(move.source.name for move in moves[:_NAMES]))
        self.names.setProperty("role", "secondary")
        top = hbox(spacing=8)
        top.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        top.addStretch(1)
        top.addWidget(self.amount, 0, Qt.AlignmentFlag.AlignTop)
        layout = vbox(self, margins=(20, 16, 20, 16), spacing=8)
        layout.addLayout(top)
        layout.addWidget(self.name)
        layout.addWidget(self.names)


class OrganizePage(QWidget):
    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        self._plan = _NO_PLAN
        self._rows: dict[int, QTreeWidgetItem] = {}
        self.cards: list[CategoryCard] = []
        self.planned_at: float | None = None
        translator = window.translator
        text = translator.text
        context = window.environment.scan_context()
        found = blockers(context.platform, context.open_files)
        self._blocked = bool(found)

        look = window.look
        why = [translator.label(blocker) for blocker in found]
        self.blocked = QLabel("\n".join([text("organize.blocked"), *why]))
        self.blocked.setWordWrap(True)
        self.blocked.setHidden(not found)
        self.controls = QWidget()

        self.folder = Field(
            look, text("organize.folder"), "folder", placeholder=text("organize.no_folder")
        )
        self.folder.setReadOnly(True)
        self.folder.setMaximumWidth(480)
        self.choose_button = button(look, text("organize.choose"))
        self.choose_button.clicked.connect(self._choose)
        self.state = Note(self.controls, role="caption")
        self.state.setWordWrap(False)
        self.summary = Note(self.controls)
        self.categories = QGridLayout()
        self.categories.setContentsMargins(0, 0, 0, 0)
        self.categories.setHorizontalSpacing(16)
        self.categories.setVerticalSpacing(16)
        for column in range(PER_ROW):
            self.categories.setColumnStretch(column, 1)
        self._fillers: list[QWidget] = []

        self.staying = QWidget()
        self.stays_title = QLabel(text("organize.stays_title"))
        self.stays_title.setProperty("role", "strong")
        self.stays_note = Note(self.staying, role="secondary")
        self.stays_note.setWordWrap(False)
        self.stays = QTreeWidget()
        rows(self.stays, look)
        self.stays.setAccessibleName(text("organize.stays_title"))
        _fits(self.stays)
        self.stays.setColumnCount(2)
        header = self.stays.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.stays.currentItemChanged.connect(self._current)
        self.detail = Note(self.staying)
        self.explain = ExplainPanel(window)
        self.explain.hide()  # until a file that stays is selected

        self.recent, recent = card()
        self.recent.setFixedWidth(BATCHES_WIDTH)
        self.recent_title = QLabel(text("batches.title"))
        self.recent_title.setProperty("role", "caption")
        self.undo_button = button(look, text("organize.undo"), icon="undo-2")
        self.undo_button.clicked.connect(self._undo)
        self.batches = QTreeWidget()
        rows(self.batches, look)
        self.batches.setAccessibleName(text("batches.title"))
        _fits(self.batches)
        self.batches.itemSelectionChanged.connect(window.update_starters)
        self.batches.hide()  # until the batches are read
        self.no_batches = Note(self.recent, role="secondary")
        self.result = Note(self.controls)

        self.will = QLabel()
        self.will.setProperty("role", "strong")
        self.safe = QLabel(text("organize.safe"))
        self.safe.setProperty("role", "secondary")
        self.safe.setWordWrap(True)
        self.move_button = button(look, text("organize.sort"), role="primary")
        self.move_button.clicked.connect(self._move)
        self.bar, inside_bar = bar()
        inside_bar.addWidget(self.will)
        inside_bar.addWidget(self.safe, 1)
        inside_bar.addWidget(self.move_button)

        chosen = hbox(spacing=8)
        chosen.addWidget(self.folder, 3)
        chosen.addWidget(self.choose_button)
        chosen.addStretch(1)
        chosen.addWidget(self.state)
        stays_head = hbox(spacing=12)
        stays_head.addWidget(self.stays_title)
        stays_head.addWidget(self.stays_note)
        stays_head.addStretch(1)
        staying = vbox(self.staying, spacing=8)
        staying.addLayout(stays_head)
        staying.addWidget(self.stays)
        staying.addWidget(self.detail)
        staying.addWidget(self.explain)
        recent_head = hbox(spacing=8)
        recent_head.addWidget(self.recent_title)
        recent_head.addStretch(1)
        recent_head.addWidget(self.undo_button)
        recent.addLayout(recent_head)
        recent.addWidget(self.batches)
        recent.addWidget(self.no_batches)
        lower = hbox(spacing=24)
        lower.addWidget(self.staying, 1, Qt.AlignmentFlag.AlignTop)
        lower.addStretch(0)
        lower.addWidget(self.recent, 0, Qt.AlignmentFlag.AlignTop)
        inside = vbox(self.controls, margins=(32, 16, 32, 16), spacing=16)
        inside.addLayout(chosen)
        inside.addWidget(self.summary)
        inside.addLayout(self.categories)
        inside.addLayout(lower)
        inside.addWidget(self.result)
        inside.addStretch(1)
        self.area = QScrollArea()
        self.area.setFrameShape(QFrame.Shape.NoFrame)
        self.area.setWidgetResizable(True)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.area.setWidget(self.controls)
        self.controls.setAutoFillBackground(False)  # setWidget fills it: the page shows through
        self.area.viewport().setAutoFillBackground(False)
        self.area.setHidden(self._blocked)

        self.head = Head(text("page.organize"), text("head.organize"))
        top = vbox(margins=(32, 32, 32, 0), spacing=16)
        top.addWidget(self.head)
        top.addWidget(self.blocked)
        layout = vbox(self, spacing=0)
        layout.addLayout(top)
        layout.addWidget(self.area, 1)
        layout.addStretch(0)
        layout.addWidget(self.bar)
        window.add_starter(self.choose_button)
        window.add_starter(self.move_button, lambda: bool(self._plan.moves))
        window.add_starter(self.undo_button, lambda: bool(self.batches.selectedItems()))
        self._show_plan()

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
        """The batches, newest first: each with its id and time, then its files moved, kind and
        state, and its folder in its tooltip; with none, that there is none."""
        translator = self._window.translator
        text = translator.text
        self.batches.clear()
        self._rows = {}
        for summary in batches:
            batch = summary.batch
            when = moment(batch.created_at_ns / 1e9)
            row = QTreeWidgetItem(
                self.batches, [text("organize.batch", batch=batch.batch_id, moment=when)]
            )
            files = translator.count("file", summary.moved)
            kind, state = self._kind(batch), self._state(summary)
            note = text("organize.batch_note", files=files, kind=kind, state=state)
            row.setData(0, SECONDARY, note)
            row.setData(0, _BATCH, batch.batch_id)
            row.setToolTip(0, shown_path(batch.folder, Path.home()))
            self._rows[batch.batch_id] = row
        self.batches.setHidden(not batches)
        self.no_batches.setText("" if batches else text("organize.no_batches"))
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
        text = self._window.translator.text
        self.result.clear()
        self._plan = _NO_PLAN
        self.planned_at = None
        self.folder.setText(shown_path(found.folder, Path.home()))
        self.choose_button.setText(text("organize.change"))
        if isinstance(found, FolderRefused):
            self._window.overview.show_plan(None)
            self._show_plan()
            self.summary.setText(self._refused(found))
            return
        self._plan = found
        self.planned_at = time.time()
        self._window.overview.show_plan(found)
        self._show_plan()

    def _show_plan(self) -> None:
        """The plan shown: a card per category, three to a row, the files that stay, the plan's
        state and the bar; with no plan, none of them."""
        window = self._window
        translator = window.translator
        text, count = translator.text, translator.count
        found = self._plan
        for widget in [*self.cards, *self._fillers]:
            self.categories.removeWidget(widget)
            widget.setParent(None)
        groups: dict[str, list[Move]] = {}
        for move in found.moves:
            groups.setdefault(move.category, []).append(move)
        self.cards = [
            CategoryCard(window.look, translator, category, moves)
            for category, moves in groups.items()
        ]
        self._fillers = [QWidget() for _ in range(-len(self.cards) % PER_ROW)]
        for filler in self._fillers:
            shares(filler)
        for index, widget in enumerate([*self.cards, *self._fillers]):
            self.categories.addWidget(widget, *divmod(index, PER_ROW))
        self.stays.clear()
        self.staying.setHidden(not found.stays)  # shown first: its rows are measured in its font
        for index, stay in enumerate(found.stays):
            reason = translator.reason(stay.reason, stay.detail)
            row = QTreeWidgetItem(self.stays, [str(stay.path.relative_to(found.folder)), reason])
            row.setData(0, _STAY, index)
            row.setTextAlignment(1, _RIGHT)
            row.setData(1, QUIET, True)
        self.stays_note.setText(text("organize.stays_note", files=count("file", len(found.stays))))
        moves = bool(found.moves)
        planned = self.planned_at
        when = "" if planned is None else moment(planned)
        self.state.setText(text("organize.state", moment=when) if moves else "")
        nothing = planned is not None and not moves
        self.summary.setText(text("organize.nothing", folder=found.folder) if nothing else "")
        into = count("folders.into", len(groups))
        self.will.setText(text("organize.will", files=count("file", len(found.moves)), into=into))
        self.bar.setHidden(not moves)
        window.update_starters()

    def _current(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:
        """The detail of the selected file that stays, and its Explain; with none, neither."""
        stay = None if current is None else self._plan.stays[int(current.data(0, _STAY))]
        self.detail.setText("" if stay is None else "\n".join(self._detail(stay)))
        self.explain.setHidden(stay is None)
        self.explain.show_for(stay)

    def _detail(self, stay: Stay) -> list[str]:
        translator = self._window.translator
        reason = translator.reason(stay.reason, stay.detail)
        return [
            translator.text("organize.path", path=stay.path),
            translator.text("organize.why", reason=reason),
        ]

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
        self.planned_at = None
        self._window.overview.show_plan(None)
        self._show_plan()
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
        batch_id = int(row.data(0, _BATCH))
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
