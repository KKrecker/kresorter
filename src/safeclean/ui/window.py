"""The window: a sidebar of six pages, the task that runs, closing (decision 0014, items 16-18).

The sidebar opens Overview, Findings, Quarantine, Organize, Autostart and Settings, in that order,
the current page marked and every page reachable with the keyboard. Every control that starts a
task is registered with ``add_starter``: it is disabled while a task runs, and otherwise enabled
when its page's own condition holds. The window says what runs, shows a task's error with its
message, and refuses to close while a task that acts runs; it closes once that task has ended.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from safeclean.environment import Environment
from safeclean.ui.dialogs import Dialogs, choose_folder, confirm
from safeclean.ui.findings import FindingsPage
from safeclean.ui.i18n import Translator
from safeclean.ui.overview import OverviewPage
from safeclean.ui.tasks import Task, Tasks
from safeclean.ui.theme import Look

__all__ = ["PAGES", "Window"]

PAGES = ("overview", "findings", "quarantine", "organize", "autostart", "settings")

T = TypeVar("T")


def _always() -> bool:
    return True


def _placeholder(title: str) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    heading = QLabel(title)
    heading.setProperty("role", "heading")
    layout.addWidget(heading)
    layout.addStretch(1)
    return page


class Window(QMainWindow):
    def __init__(
        self, environment: Environment, translator: Translator, dialogs: Dialogs | None = None
    ) -> None:
        """``dialogs``: the window's own, unless a test answers them."""
        super().__init__()
        self.environment = environment
        self.translator = translator
        self.dialogs = dialogs or Dialogs(
            confirm=functools.partial(confirm, self, translator),
            choose_folder=functools.partial(choose_folder, self, translator, Path.home()),
        )
        self.setWindowTitle(translator.text("app.title"))
        self._starters: list[tuple[QWidget, Callable[[], bool]]] = []
        self._close_when_done = False

        self.tasks = Tasks(self)
        self.tasks.busy.connect(self._busy)
        self.tasks.failed.connect(self._failed)

        self.overview = OverviewPage(self)
        self.findings = FindingsPage(self)
        made: dict[str, QWidget] = {"overview": self.overview, "findings": self.findings}
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.pages = QStackedWidget()
        self._pages: list[QWidget] = []
        for name in PAGES:
            title = translator.text(f"page.{name}")
            self.sidebar.addItem(title)
            self._pages.append(made.get(name) or _placeholder(title))
            self.pages.addWidget(self._pages[-1])
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

        self.message = QLabel()
        self.message.setObjectName("message")
        self.message.setWordWrap(True)
        self.status = QLabel()
        self.status.setObjectName("task-status")
        self.status.setProperty("role", "secondary")

        right = QVBoxLayout()
        right.addWidget(self.pages, 1)
        right.addWidget(self.message)
        right.addWidget(self.status)
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(self.sidebar)
        layout.addLayout(right, 1)
        self.setCentralWidget(central)
        Look(self)

    def page(self, name: str) -> QWidget:
        return self._pages[PAGES.index(name)]

    def show_page(self, name: str) -> None:
        self.sidebar.setCurrentRow(PAGES.index(name))

    def add_starter(self, control: QWidget, when: Callable[[], bool] = _always) -> None:
        """``control`` starts a task: enabled only while none runs and ``when()`` holds."""
        self._starters.append((control, when))
        self.update_starters()

    def update_starters(self) -> None:
        idle = self.tasks.running is None
        for control, when in self._starters:
            control.setEnabled(idle and when())

    def run(self, task: Task[T]) -> bool:
        """Start ``task``; ``False`` while another runs."""
        if not self.tasks.start(task):
            return False
        self.message.clear()
        return True

    def _busy(self, running: bool) -> None:
        task = self.tasks.running
        what = "" if task is None else self.translator.text("task.running", task=task.title)
        self.status.setText(what)
        self.update_starters()
        if not running and self._close_when_done:
            self.close()

    def _failed(self, title: str, message: str) -> None:
        self.message.setText(self.translator.text("task.failed", task=title, message=message))

    def closeEvent(self, event: QCloseEvent) -> None:
        holding = self.tasks.holding()
        if holding is not None:
            self._close_when_done = True
            self.message.setText(self.translator.text("close.wait", task=holding.title))
            event.ignore()
            return
        self.tasks.abandon()
        event.accept()
