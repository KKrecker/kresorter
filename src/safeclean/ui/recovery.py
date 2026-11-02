"""Unfinished work: the banner that offers Recover, and what each recovery closed, in the
window's words (decision 0014, items 2, 3, 13 and 25).

When the window opens on a journal that is already there, it looks for unfinished work (no
journal: nothing is opened, nothing created); a session that finds some, of another domain or
an autostart change it cannot close, offers it too. The banner names the domains and offers
Recover, which asks first, saying what recovery finishes in each, then runs what ``safeclean
recover`` runs and shows what was closed, as that command reports it. A session that closed its
own domain's unfinished work shows that here as well.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton

from safeclean.autostart.journal import ChangeRecovery, ChangeState
from safeclean.organize import recovery as organize_recovery
from safeclean.organize.journal import BatchKind, BatchState
from safeclean.quarantine.recovery import RecoveryReport
from safeclean.storage.pending import Domain
from safeclean.storage.session import SessionFailed
from safeclean.ui.dialogs import Confirmation
from safeclean.ui.i18n import Translator
from safeclean.ui.parts import hbox
from safeclean.ui.sessions import (
    ORDER,
    Recovered,
    Unclosed,
    domains,
    problem,
    recover_all,
    unfinished_work,
)
from safeclean.ui.tasks import Task

if TYPE_CHECKING:
    from safeclean.ui.window import Window

__all__ = [
    "RecoveryBanner",
    "autostart_lines",
    "organize_lines",
    "quarantine_lines",
    "recovered_lines",
]


def quarantine_lines(translator: Translator, report: RecoveryReport) -> list[str]:
    """As ``safeclean recover`` reports the quarantine's: the files, then each warning."""
    found = report.quarantined + report.rolled_back + report.restored + report.purged
    found += report.lost
    files = translator.count("file", len(found))
    head = [translator.text("recovered.quarantine", files=files)] if found else []
    return [*head, *report.warnings]


def organize_lines(translator: Translator, report: organize_recovery.RecoveryReport) -> list[str]:
    """Each batch closed, its state and what is still sorted, then each warning."""
    text = translator.text
    lines = [text("recovered.organize", n=len(report.batches))] if report.batches else []
    for batch in report.batches:
        state = translator.label(batch.state)
        if batch.kind is BatchKind.UNDO:
            undoing = batch.undoing
            lines.append(text("recovered.undo", batch=batch.batch_id, undoing=undoing, state=state))
            stopped = batch.state is not BatchState.DONE
            lines += [text("undo.again", batch=undoing)] if stopped else []
            continue
        lines.append(text("recovered.batch", batch=batch.batch_id, state=state))
        lines += [text("organize.still", path=path) for path in batch.left]
        lines += [text("organize.left", batch=batch.batch_id)] if batch.left else []
    return [*lines, *report.warnings]


def autostart_lines(translator: Translator, recovered: ChangeRecovery | Unclosed) -> list[str]:
    """Each change closed, by its id, with its end; or why one stays unfinished."""
    if isinstance(recovered, Unclosed):
        return [problem(translator, recovered)]
    closed = [(change, ChangeState.DONE) for change in recovered.done]
    closed += [(change, ChangeState.ROLLED_BACK) for change in recovered.rolled_back]
    closed += [(change, ChangeState.FAILED) for change in recovered.failed]
    head = [translator.text("recovered.autostart", n=len(closed))] if closed else []
    return head + [
        translator.text("recovered.change", change=change, state=translator.label(state))
        for change, state in sorted(closed)
    ]


def recovered_lines(translator: Translator, recovered: Recovered) -> list[str]:
    """What Recover closed, domain by domain, or that there was nothing."""
    lines = quarantine_lines(translator, recovered.quarantine)
    lines += organize_lines(translator, recovered.organize)
    lines += autostart_lines(translator, recovered.autostart)
    return lines or [translator.text("recovered.nothing")]


class RecoveryBanner(QFrame):
    """Above the pages: what was last closed, then the domains still offered to Recover; hidden
    while there is neither, and when the user hides it, until there is something new."""

    def __init__(self, window: Window) -> None:
        super().__init__()
        self._window = window
        self._closed: list[str] = []
        self._offered: frozenset[Domain] = frozenset()
        text = window.translator.text
        self.setProperty("role", "banner")
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.recover_button = QPushButton(text("recover.button"))
        self.recover_button.setProperty("role", "primary")
        self.recover_button.clicked.connect(self._recover)
        self.hide_button = QPushButton(text("recover.hide"))
        self.hide_button.clicked.connect(self.hide)
        layout = hbox(self, margins=(16, 12, 16, 12), spacing=8)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.recover_button)
        layout.addWidget(self.hide_button)
        window.add_starter(self.recover_button)
        self._show()

    @property
    def offered(self) -> frozenset[Domain]:
        return self._offered

    def offer(self, found: Collection[Domain]) -> None:
        """Offer Recover for ``found``: every domain a session found unfinished."""
        self._closed, self._offered = [], frozenset(found)
        self._show()

    def report(self, domain: Domain, lines: list[str]) -> None:
        """A session of ``domain`` recovered its unfinished work first: what it closed, if
        anything, is shown, and ``domain`` is no longer offered."""
        if lines or domain in self._offered:
            self._closed = lines
            self._offered -= {domain}
            self._show()

    def look(self) -> None:
        """Look for unfinished work in the journal, if there is one."""
        window = self._window
        environment = window.environment

        def work() -> frozenset[Domain]:
            return unfinished_work(environment.scan_context())

        def done(found: frozenset[Domain]) -> None:
            if found:
                self.offer(found)

        window.run(Task(window.translator.text("task.look"), work, done, acts=True))

    def _show(self) -> None:
        translator = self._window.translator
        found = translator.text("recover.found", domains=domains(translator, self._offered))
        lines = [*self._closed, *([found] if self._offered else [])]
        self.text.setText("\n".join(lines))
        self.recover_button.setVisible(bool(self._offered))
        self.setVisible(bool(lines))

    def _recover(self) -> None:
        window, translator = self._window, self._window.translator
        offered = [domain for domain in ORDER if domain in self._offered]
        action = translator.text("recover.action")
        asked = Confirmation(
            title=action,
            text=translator.text("recover.confirm", domains=domains(translator, offered)),
            details=tuple(translator.text(f"recover.{domain}") for domain in offered),
            action=action,
        )
        if not window.dialogs.confirm(asked):
            return
        environment = window.environment

        def work() -> Recovered | SessionFailed:
            return recover_all(environment.scan_context(), environment.autostart_context())

        window.run(Task(translator.text("task.recover"), work, self._recovered, acts=True))

    def _recovered(self, outcome: Recovered | SessionFailed) -> None:
        translator = self._window.translator
        if isinstance(outcome, SessionFailed):
            self._closed = [problem(translator, outcome)]
        else:
            self._closed = recovered_lines(translator, outcome)
            self._offered = outcome.left
        self._show()
