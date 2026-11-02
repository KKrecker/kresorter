"""The Autostart page: the entries grouped by source, Disable and Enable after confirmation
(decision 0014, items 3, 13, 24, 26 and 37).

The entries are read each time the page opens, and on Refresh, as ``autostart list`` reads them:
nothing is opened, created or changed. On Windows the machine scope is read only when the setting
says so (``ui.settings``), as ``--include-machine`` reads it, and otherwise the page says what was
not read. Each group names its source and its count; each entry shows its state, scope and location,
and the detail of the selected entry its command, the system entry it replaces and its conditions,
with Explain (local AI) (``ui.explain``). Disable or Enable is offered for an entry that can change
(``disableable``) and is not in that state already; the confirmation says what is written, as
``autostart disable`` without ``--yes`` does. Confirmed, the change runs in a session
(``ui.sessions``) that recovers autostart's own unfinished changes first, and its changer refuses an
entry that is no longer the one listed. The result says done, refused, rolled back or failed; a
failed change, and one left unfinished, names Recover, which the banner offers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QWidget

from safeclean.autostart.journal import ChangeResult, ChangeState
from safeclean.autostart.listing import AutostartContext, list_autostart
from safeclean.autostart.models import AutostartItem, AutostartListing, Scope, Source
from safeclean.autostart.xdg import autostart_dirs
from safeclean.storage.pending import Domain
from safeclean.storage.session import SessionFailed
from safeclean.ui.dialogs import Confirmation
from safeclean.ui.explain import ExplainPanel
from safeclean.ui.parts import Head, Note, button, hbox, page, rows
from safeclean.ui.recovery import autostart_lines
from safeclean.ui.sessions import (
    Action,
    Changed,
    NotChanged,
    Unclosed,
    Unfinished,
    change_entry,
)
from safeclean.ui.tasks import Task

if TYPE_CHECKING:
    from safeclean.ui.window import Window

__all__ = ["AutostartPage"]

_INDEX = Qt.ItemDataRole.UserRole  # an entry's place in the listing
_COLUMNS = ("name", "state", "scope", "location")


class AutostartPage(QWidget):
    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        self._items: tuple[AutostartItem, ...] = ()
        self._rows: list[QTreeWidgetItem] = []
        self._windows = window.environment.autostart_context().platform == "windows"
        text = window.translator.text

        look = window.look
        self.entries = QTreeWidget()
        rows(self.entries, look)
        self.entries.setAccessibleName(text("autostart.entries"))
        self.entries.setColumnCount(len(_COLUMNS))
        self.entries.setHeaderLabels([text(f"autostart.{name}") for name in _COLUMNS])
        self.entries.itemSelectionChanged.connect(self._selected)
        self.total = Note(self, role="secondary")
        self.machine = QLabel(text("autostart.machine"))
        self.machine.setWordWrap(True)
        self.machine.setHidden(True)
        self.skipped = Note(self, role="secondary")
        self.detail = Note(self)
        self.explain = ExplainPanel(window)
        self.refresh_button = button(look, text("autostart.refresh"), icon="refresh-cw")
        self.refresh_button.clicked.connect(self.load)
        self.disable_button = button(look, text("autostart.disable"))
        self.disable_button.clicked.connect(lambda: self._confirm("disable"))
        self.enable_button = button(look, text("autostart.enable"))
        self.enable_button.clicked.connect(lambda: self._confirm("enable"))
        self.result = Note(self)

        buttons = hbox(spacing=8)
        buttons.addStretch(1)
        buttons.addWidget(self.disable_button)
        buttons.addWidget(self.enable_button)
        head = Head(text("page.autostart"), text("head.autostart"), self.refresh_button)
        layout = page(self, head)
        layout.addWidget(self.entries, 1)
        layout.addWidget(self.total)
        layout.addWidget(self.machine)
        layout.addWidget(self.skipped)
        layout.addWidget(self.detail)
        layout.addWidget(self.explain)
        layout.addLayout(buttons)
        layout.addWidget(self.result)
        window.add_starter(self.refresh_button)
        window.add_starter(self.disable_button, lambda: self._can("disable"))
        window.add_starter(self.enable_button, lambda: self._can("enable"))

    def row(self, name: str) -> QTreeWidgetItem:
        """The first entry named ``name``."""
        return next(row for row in self._rows if row.text(0) == name)

    def selected(self) -> AutostartItem | None:
        rows = self.entries.selectedItems()
        return self._item(rows[0]) if rows else None

    def _can(self, action: Action) -> bool:
        item = self.selected()
        return item is not None and item.disableable and item.enabled is (action == "disable")

    # --- the listing ---------------------------------------------------------------------------

    def load(self) -> None:
        """Read the entries again, with the machine scope as the setting says; no journal is
        opened."""
        window = self._window
        environment = window.environment
        machine = window.settings.current.include_machine

        def work() -> AutostartListing:
            return list_autostart(environment.autostart_context(), include_machine=machine)

        def done(listing: AutostartListing) -> None:
            self.result.clear()
            self._list(listing, machine)

        window.run(Task(window.translator.text("task.autostart"), work, done))

    def _list(self, listing: AutostartListing, machine: bool) -> None:
        """Show ``listing``, grouped by source, read with the machine scope when ``machine``;
        the entry selected stays selected while one of the same source and name is there."""
        translator = self._window.translator
        text = translator.text
        chosen = self.selected()
        self.entries.clear()
        self._items, self._rows = listing.items, []
        groups: dict[Source, QTreeWidgetItem] = {}
        for index, item in enumerate(listing.items):
            group = groups.get(item.source)
            if group is None:
                group = groups[item.source] = QTreeWidgetItem(self.entries)
                group.setFlags(Qt.ItemFlag.ItemIsEnabled)
                group.setFirstColumnSpanned(True)
                group.setExpanded(True)
            row = QTreeWidgetItem(group, self._cells(item))
            row.setData(0, _INDEX, index)
            self._rows.append(row)
        for source, group in groups.items():
            found = group.childCount()
            group.setText(0, text("autostart.group", source=translator.label(source), n=found))
        for column in range(self.entries.columnCount()):
            self.entries.resizeColumnToContents(column)
        entries = translator.count("entry", len(listing.items))
        disabled = sum(not item.enabled for item in listing.items)
        self.total.setText(text("autostart.total", entries=entries, disabled=disabled))
        self._window.overview.show_autostart((len(listing.items), disabled))
        skipped = [text("autostart.skipped", n=len(listing.skipped))]
        skipped += [
            text(
                "autostart.skip",
                source=translator.label(skip.source),
                location=skip.location,
                detail=skip.detail,
            )
            for skip in listing.skipped
        ]
        self.skipped.setText("\n".join(skipped))
        self.machine.setHidden(machine or not self._windows)
        again = [row for row in self._rows if chosen is not None and _same(self._item(row), chosen)]
        if again:
            again[0].setSelected(True)
        self._window.update_starters()

    def _cells(self, item: AutostartItem) -> list[str]:
        translator = self._window.translator
        state = translator.text("entry.enabled" if item.enabled else "entry.disabled")
        return [item.name, state, translator.label(item.scope), item.location]

    def _item(self, row: QTreeWidgetItem) -> AutostartItem:
        return self._items[int(row.data(0, _INDEX))]

    def _selected(self) -> None:
        item = self.selected()
        self.detail.setText("" if item is None else "\n".join(self._detail(item)))
        self.explain.show_for(item)

    def _detail(self, item: AutostartItem) -> list[str]:
        """The command, the system entry it replaces and its conditions, as they are."""
        text = self._window.translator.text
        lines = [text("entry.command", command=item.command)]
        if item.shadows is not None:
            lines.append(text("entry.shadows", shadows=item.shadows))
        return lines + [text("entry.note", note=note) for note in item.notes]

    # --- a change ------------------------------------------------------------------------------

    def _confirm(self, action: Action) -> None:
        window, translator = self._window, self._window.translator
        text = translator.text
        [row] = self.entries.selectedItems()  # enabled with one entry selected, the most there is
        item = self._item(row)
        context = window.environment.autostart_context()
        named = {"name": item.name, "source": translator.label(item.source)}
        asked = Confirmation(
            title=text(f"change.{action}_title", name=item.name),
            text=text(f"change.{action}_confirm", scope=translator.label(item.scope), **named),
            details=(
                text("change.location", location=item.location),
                self._how(action, item, context),
            ),
            action=text(f"change.{action}"),
        )
        if not window.dialogs.confirm(asked):
            return
        scan = window.environment.scan_context
        machine = window.settings.current.include_machine

        def work() -> Changed | Unclosed | Unfinished | SessionFailed:
            return change_entry(scan(), context, action, item, include_machine=machine)

        def done(outcome: Changed | Unclosed | Unfinished | SessionFailed) -> None:
            self._changed(outcome, action, item, machine)

        window.run(Task(text(f"task.{action}"), work, done, acts=True))

    def _how(self, action: Action, item: AutostartItem, context: AutostartContext) -> str:
        """What the change writes, as ``autostart disable`` and ``enable`` say it."""
        text = self._window.translator.text
        if item.source is Source.RUN_KEY:
            return text(f"how.run_key_{action}")
        if action == "enable":
            return text("how.enable")
        if item.scope is Scope.USER:
            return text("how.user_disable")
        user, _ = autostart_dirs(context.env, context.home)
        return text("how.system_disable", folder=user)

    def _changed(
        self,
        outcome: Changed | Unclosed | Unfinished | SessionFailed,
        action: Action,
        item: AutostartItem,
        machine: bool,
    ) -> None:
        window = self._window
        if not isinstance(outcome, Changed):
            self.result.setText(window.refusal(outcome))
            return
        window.recovery.report(
            Domain.AUTOSTART, autostart_lines(window.translator, outcome.recovered)
        )
        self._list(outcome.listing, machine)
        self.result.setText(self._result(outcome.result, action, item))

    def _result(
        self, result: ChangeResult | NotChanged | Unclosed, action: Action, item: AutostartItem
    ) -> str:
        window = self._window
        translator, text = window.translator, window.translator.text
        if isinstance(result, NotChanged):
            return text("change.not_changed", name=item.name, detail=result.detail)
        if isinstance(result, Unclosed):
            return window.refusal(result)
        if result.refusal is not None:
            return text("change.refused", reason=translator.label(result.refusal))
        change = result.change_id
        if result.state is ChangeState.DONE:
            return text(f"change.{action}d", name=item.name, change=change)
        if result.state is ChangeState.ROLLED_BACK:
            return text("change.rolled_back", detail=result.detail, change=change)
        window.recovery.offer(window.recovery.offered | {Domain.AUTOSTART})
        return text("change.failed", detail=result.detail, change=change)


def _same(one: AutostartItem, other: AutostartItem) -> bool:
    return (one.source, one.name) == (other.source, other.name)
