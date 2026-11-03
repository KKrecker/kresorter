"""The Autostart page: the entries grouped by source, each turned by its switch after
confirmation (decision 0014, items 3, 13, 24, 26, 37 and 53).

The entries are read each time the page opens, and on Refresh, as ``autostart list`` reads them:
nothing is opened, created or changed. On Windows the machine scope is read only when the setting
says so (``ui.settings``), as ``--include-machine`` reads it, and otherwise the page says what was
not read. A section per source names it and its count; a row per entry has a tile with its
initial, its name and under it its location (from the home folder as ``~``), its scope as a
badge and a switch that is on when it starts. The search field in the head keeps the entries
whose name or location contains its text, ignoring case. The detail of the selected entry, under
the list, has its command, the system entry it replaces and its conditions, with Explain (local
AI) (``ui.explain``). The switch of an entry that can change (``disableable``) asks to disable or
enable it; the confirmation says what is written, as ``autostart disable`` without ``--yes``
does. The switch of one that cannot has a lock and does not turn. Confirmed, the change runs in a
session (``ui.sessions``) that recovers autostart's own unfinished changes first, and its changer
refuses an entry that is no longer the one listed. The result says done, refused, rolled back or
failed; a failed change, and one left unfinished, names Recover, which the banner offers. No
switch turns while a task runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QLabel, QTreeWidget, QTreeWidgetItem, QWidget

from kresorter.autostart.journal import ChangeResult, ChangeState
from kresorter.autostart.listing import AutostartContext, list_autostart
from kresorter.autostart.models import AutostartItem, AutostartListing, Scope, Source
from kresorter.autostart.xdg import autostart_dirs
from kresorter.storage.pending import Domain
from kresorter.storage.session import SessionFailed
from kresorter.ui.dialogs import Confirmation
from kresorter.ui.explain import ExplainPanel
from kresorter.ui.parts import (
    BADGE,
    EMPHASIS,
    INITIAL,
    QUIET,
    SECONDARY,
    SWITCH_SIZE,
    Field,
    Head,
    Icon,
    Note,
    Switch,
    button,
    hbox,
    page,
    rows,
    secondary_ink,
)
from kresorter.ui.recovery import autostart_lines
from kresorter.ui.sessions import (
    Action,
    Changed,
    NotChanged,
    Unclosed,
    Unfinished,
    change_entry,
)
from kresorter.ui.shown import shown_path
from kresorter.ui.tasks import Task

if TYPE_CHECKING:
    from kresorter.ui.window import Window

__all__ = ["SEARCH_WIDTH", "SWITCH_COLUMN", "AutostartPage"]

_INDEX = Qt.ItemDataRole.UserRole  # an entry's place in the listing
_ENTRY, _SCOPE, _SWITCH = range(3)  # the columns
SEARCH_WIDTH = 240  # px: the search field in the head
SWITCH_COLUMN = 16 + 8 + SWITCH_SIZE.width() + 12  # px: a lock, the switch, the cell's padding


class AutostartPage(QWidget):
    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        self._items: tuple[AutostartItem, ...] = ()
        self._rows: list[QTreeWidgetItem] = []
        self._switches: list[tuple[Switch, AutostartItem]] = []
        self._groups: list[QTreeWidgetItem] = []
        self._windows = window.environment.autostart_context().platform == "windows"
        text = window.translator.text

        look = window.look
        self.search = Field(look, text("autostart.search"), "search")
        self.search.setFixedWidth(SEARCH_WIDTH)
        self.search.textChanged.connect(self._filter)
        self.entries = QTreeWidget()
        rows(self.entries, look)
        self.entries.setAccessibleName(text("autostart.entries"))
        self.entries.setColumnCount(3)
        self.entries.setHeaderHidden(True)
        self.entries.setRootIsDecorated(False)
        self.entries.setItemsExpandable(False)
        self.entries.setIndentation(0)
        header = self.entries.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_ENTRY, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_SCOPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_SWITCH, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(_SWITCH, SWITCH_COLUMN)
        self.entries.itemSelectionChanged.connect(self._selected)
        self.total = Note(self, role="secondary")
        self.machine = QLabel(text("autostart.machine"))
        self.machine.setWordWrap(True)
        self.machine.setHidden(True)
        self.skipped = Note(self, role="secondary")
        self.detail = Note(self)
        self.explain = ExplainPanel(window)
        self.explain.hide()  # until an entry is selected
        self.refresh_button = button(look, text("autostart.refresh"), icon="refresh-cw")
        self.refresh_button.clicked.connect(self.load)
        self.result = Note(self)

        head = Head(
            text("page.autostart"), text("head.autostart"), self.search, self.refresh_button
        )
        layout = page(self, head)
        layout.addWidget(self.entries, 1)
        layout.addWidget(self.detail)
        layout.addWidget(self.explain)
        layout.addWidget(self.result)
        layout.addWidget(self.total)
        layout.addWidget(self.machine)
        layout.addWidget(self.skipped)
        window.add_starter(self.refresh_button)
        window.tasks.busy.connect(self._busy)

    def row(self, name: str) -> QTreeWidgetItem:
        """The first entry named ``name``."""
        return next(row for row in self._rows if row.text(_ENTRY) == name)

    def switch(self, name: str) -> Switch:
        """The switch of the first entry named ``name``."""
        return next(made for made, item in self._switches if item.name == name)

    def selected(self) -> AutostartItem | None:
        rows = self.entries.selectedItems()
        return self._item(rows[0]) if rows else None

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
        """Show ``listing``, a section per source, read with the machine scope when
        ``machine``; the entry selected stays selected while one of the same source and name is
        there."""
        translator = self._window.translator
        text = translator.text
        chosen = self.selected()
        self.entries.clear()
        self._items, self._rows, self._switches = listing.items, [], []
        groups: dict[Source, QTreeWidgetItem] = {}
        for index, item in enumerate(listing.items):
            group = groups.get(item.source)
            if group is None:
                group = groups[item.source] = QTreeWidgetItem(self.entries)
                group.setFlags(Qt.ItemFlag.ItemIsEnabled)
                group.setFirstColumnSpanned(True)
                group.setExpanded(True)
                group.setData(_ENTRY, EMPHASIS, True)
                group.setData(_ENTRY, QUIET, True)
            row = QTreeWidgetItem(group, [item.name, translator.label(item.scope)])
            row.setData(_ENTRY, _INDEX, index)
            row.setData(_ENTRY, EMPHASIS, True)
            row.setData(_ENTRY, SECONDARY, shown_path(Path(item.location), Path.home()))
            row.setData(_ENTRY, INITIAL, item.name[:1].upper())
            row.setToolTip(_ENTRY, item.location)
            row.setData(_SCOPE, BADGE, "advisory")
            self.entries.setItemWidget(row, _SWITCH, self._switch(item, row))
            self._rows.append(row)
        self._groups = list(groups.values())
        for source, group in groups.items():
            entries = translator.count("entry", group.childCount())
            named = translator.label(source)
            group.setText(_ENTRY, text("autostart.group", source=named, entries=entries))
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
        self._filter()

    def _switch(self, item: AutostartItem, row: QTreeWidgetItem) -> QWidget:
        """The entry's switch, on when it starts, and the lock of an entry that cannot change."""
        window = self._window
        text = window.translator.text
        holder = QWidget()
        layout = hbox(holder, margins=(0, 0, 12, 0), spacing=8)
        layout.addStretch(1)
        if not item.disableable:
            lock = Icon(window.look, "lock", secondary_ink)
            lock.setToolTip(text("autostart.locked"))
            layout.addWidget(lock)
        made = Switch(window.look, item.name)
        made.setChecked(item.enabled)
        made.setToolTip(text("entry.enabled" if item.enabled else "entry.disabled"))
        made.setEnabled(item.disableable and window.tasks.running is None)
        made.clicked.connect(lambda _=False: self._turn(row))
        layout.addWidget(made)
        self._switches.append((made, item))
        return holder

    def _busy(self, running: bool) -> None:
        """No switch turns while a task runs."""
        for made, item in self._switches:
            made.setEnabled(item.disableable and not running)

    def _filter(self) -> None:
        """Keep the entries whose name or location contains the search's text, ignoring case,
        and the sections that keep one; an entry put away is no longer selected."""
        needle = self.search.text().casefold()
        for row in self._rows:
            item = self._item(row)
            away = needle not in item.name.casefold() and needle not in item.location.casefold()
            row.setHidden(away)
            if away:
                row.setSelected(False)
        for group in self._groups:
            kept = [row for row in self._rows if row.parent() is group]
            group.setHidden(all(row.isHidden() for row in kept))

    def _item(self, row: QTreeWidgetItem) -> AutostartItem:
        return self._items[int(row.data(_ENTRY, _INDEX))]

    def _selected(self) -> None:
        item = self.selected()
        self.detail.setText("" if item is None else "\n".join(self._detail(item)))
        self.explain.setHidden(item is None)
        self.explain.show_for(item)

    def _detail(self, item: AutostartItem) -> list[str]:
        """The command, the system entry it replaces and its conditions, as they are."""
        text = self._window.translator.text
        lines = [text("entry.command", command=item.command)]
        if item.shadows is not None:
            lines.append(text("entry.shadows", shadows=item.shadows))
        return lines + [text("entry.note", note=note) for note in item.notes]

    # --- a change ------------------------------------------------------------------------------

    def _turn(self, row: QTreeWidgetItem) -> None:
        """The entry's switch was clicked: select the entry, and ask to turn it."""
        self.entries.clearSelection()
        row.setSelected(True)
        item = self._item(row)
        self._confirm("disable" if item.enabled else "enable", item)

    def _confirm(self, action: Action, item: AutostartItem) -> None:
        window, translator = self._window, self._window.translator
        text = translator.text
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
