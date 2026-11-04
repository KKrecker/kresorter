"""The window: a sidebar of six pages, the task that runs, closing, unfinished work (decision
0014, items 16-18, 25 and 45).

The sidebar (``ui.sidebar``) opens Overview, Findings, Organize, Autostart and Quarantine, in
that order, and Settings apart at its bottom, the current page marked and every page reachable
with the keyboard; its status lines say whether the open-file check is reliable and which model
the local AI uses. Every control that starts a
task is registered with ``add_starter``: it is disabled while a task runs, and otherwise enabled
when its page's own condition holds. The window says what runs, shows a task's error with its
message, and refuses to close while a task that acts runs; it closes once that task has ended.
Above the pages, the recovery banner offers Recover when the window opens on a journal with
unfinished work, and whenever a session finds some (``refusal``). The window opens with the
settings of the data directory (``ui.settings``); the Settings page keeps them as remembered.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QWidget

from kresorter.environment import Environment
from kresorter.llm.failure import SettingRefused
from kresorter.llm.settings import model_from
from kresorter.storage.pending import Domain
from kresorter.storage.session import SessionFailed
from kresorter.ui.autostart import AutostartPage
from kresorter.ui.dialogs import Dialogs, choose_folder, confirm
from kresorter.ui.findings import FindingsPage
from kresorter.ui.i18n import Translator
from kresorter.ui.organize import OrganizePage
from kresorter.ui.overview import OverviewPage
from kresorter.ui.parts import Note, hbox, vbox
from kresorter.ui.quarantine import QuarantinePage
from kresorter.ui.recovery import RecoveryBanner
from kresorter.ui.sessions import NoReliableCheck, Unclosed, Unfinished, problem
from kresorter.ui.settings import Loaded, load
from kresorter.ui.settings_page import SettingsPage
from kresorter.ui.sidebar import Sidebar
from kresorter.ui.tasks import Task, Tasks
from kresorter.ui.theme import Look

__all__ = ["PAGES", "Window"]

PAGES = ("overview", "findings", "organize", "autostart", "quarantine", "settings")
PROGRESS_MS = 100  # the status line counts the files read at most ten times a second (0018)

T = TypeVar("T")


def _always() -> bool:
    return True


class Window(QMainWindow):
    def __init__(
        self,
        environment: Environment,
        translator: Translator,
        dialogs: Dialogs | None = None,
        loaded: Loaded | None = None,
    ) -> None:
        """``dialogs``: the window's own, unless a test answers them; ``loaded``: the settings
        the window opens with, read from the data directory unless given."""
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
        self.progress_timer = QTimer(self)  # the files read, at most ten times a second
        self.progress_timer.setInterval(PROGRESS_MS)
        self.progress_timer.timeout.connect(self._show_task)
        self.tasks.failed.connect(self._failed)
        self.look = Look(self)

        self.sidebar = Sidebar(translator, self.look, PAGES[:-1], PAGES[-1:])
        self.recovery = RecoveryBanner(self)
        self.settings = SettingsPage(self, loaded or load(environment.scan_context()))
        self.overview = OverviewPage(self)
        self.findings = FindingsPage(self)
        self.quarantine = QuarantinePage(self)
        self.organize = OrganizePage(self)
        self.autostart = AutostartPage(self)
        made: dict[str, QWidget] = {
            "overview": self.overview,
            "findings": self.findings,
            "organize": self.organize,
            "autostart": self.autostart,
            "quarantine": self.quarantine,
            "settings": self.settings,
        }
        self.pages = QStackedWidget()
        stack = self.pages.layout()
        assert stack is not None
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        self._pages: list[QWidget] = []
        for name in PAGES:
            self._pages.append(made[name])
            self.pages.addWidget(self._pages[-1])
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.currentRowChanged.connect(self._opened)
        self.sidebar.setCurrentRow(0)
        self._show_status()

        central = QWidget()
        self.message = Note(central)
        self.message.setObjectName("message")
        self.status = Note(central, role="secondary")
        self.status.setObjectName("task-status")
        right = vbox()
        right.addWidget(self.recovery)
        right.addWidget(self.pages, 1)
        right.addWidget(self.message)
        right.addWidget(self.status)
        layout = hbox(central)
        layout.addWidget(self.sidebar)
        layout.addLayout(right, 1)
        self.setCentralWidget(central)
        self.recovery.look()

    def _show_status(self) -> None:
        """The sidebar's status lines: the open-file check, and the local AI's model."""
        text = self.translator.text
        reliable = self.environment.scan_context().open_files_checked
        key = "sidebar.open_files" if reliable else "sidebar.no_open_files"
        self.sidebar.show_open_files(text(key), reliable=reliable)
        self.show_ai(None)

    def show_ai(self, checked: bool | None) -> None:
        """The local AI's line: its model; ``checked`` as the Settings page last found it."""
        text = self.translator.text
        try:
            line = text("sidebar.ai", model=model_from(self.environment.llm_env))
        except SettingRefused as refused:
            line = text("sidebar.ai_refused", name=refused.name)
        self.sidebar.show_ai(line, checked=checked)

    def page(self, name: str) -> QWidget:
        return self._pages[PAGES.index(name)]

    def show_page(self, name: str) -> None:
        self.sidebar.setCurrentRow(PAGES.index(name))

    def _opened(self, row: int) -> None:
        """The Quarantine and Organize pages read the journal each time they open, the
        Autostart page its entries."""
        loads = {
            "quarantine": self.quarantine.load,
            "organize": self.organize.load,
            "autostart": self.autostart.load,
        }
        load = loads.get(PAGES[row])
        if load is not None:
            load()

    def refusal(
        self,
        outcome: Unfinished | NoReliableCheck | Unclosed | SessionFailed,
        *,
        no_check: str = "session.no_check",
    ) -> str:
        """Why a page's session did not act (``sessions.problem``); unfinished work it found is
        offered to Recover."""
        if isinstance(outcome, Unfinished):
            self.recovery.offer(outcome.domains)
        if isinstance(outcome, Unclosed):  # what else is unfinished is not known yet
            self.recovery.offer(self.recovery.offered | {Domain.AUTOSTART})
        return problem(self.translator, outcome, no_check=no_check)

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
        self._show_task()
        if task is not None and task.read is not None:
            self.progress_timer.start()
        else:
            self.progress_timer.stop()
        self.update_starters()
        if not running and self._close_when_done:
            self.close()

    def _show_task(self) -> None:
        """What runs, and the files it read so far when it counts them."""
        task, translator = self.tasks.running, self.translator
        files = None if task is None or task.read is None else task.read.files
        if task is None:
            what = ""
        elif files is None:
            what = translator.text("task.running", task=task.title)
        else:
            read = translator.count("read", files)
            what = translator.text("task.read", task=task.title, read=read)
        self.status.setText(what)

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
