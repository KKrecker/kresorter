"""The window's work, off its thread and one task at a time (decision 0014, items 15-17).

A task's work runs in a worker thread of its own, a daemon thread: a task that only reads is
left behind when the window closes. Its result, or the error that stopped it, comes back
through a queued signal and is applied in the window's thread. While a task runs no other
starts. A task that acts (it opens the journal) holds the window open; once the window gives up
its tasks, every result still to come is dropped.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from PySide6.QtCore import QObject, Signal

__all__ = ["Read", "Task", "Tasks"]

T = TypeVar("T")


class Read:
    """The files a task's work has read so far: called in the worker, ``files`` read in the
    window's thread (decision 0018, item 16); None before the first count."""

    def __init__(self) -> None:
        self.files: int | None = None

    def __call__(self, files: int) -> None:
        self.files = files


@dataclass(frozen=True, eq=False)
class Task(Generic[T]):
    """``work`` runs in the worker, ``done`` takes its result in the window's thread; ``title``
    says what runs. ``acts``: the task opens the journal, and closing waits for it. ``read``:
    what the work counts as it reads, shown while it runs."""

    title: str
    work: Callable[[], T]
    done: Callable[[T], None]
    acts: bool = False
    read: Read | None = None


@dataclass(frozen=True)
class _Failed:
    message: str


def _message(error: Exception) -> str:
    return str(error) or type(error).__name__


class _Relay(QObject):
    """Lives in the window's thread, without a parent: a worker that outlives the window
    still emits on it, and Qt drops what no receiver is left to take."""

    ended = Signal(object, object)


def _work(relay: _Relay, task: Task[Any]) -> None:
    """In the worker thread."""
    try:
        outcome: object = task.work()
    except Exception as error:  # shown in the window, which stays usable (item 16)
        outcome = _Failed(_message(error))
    relay.ended.emit(task, outcome)


class Tasks(QObject):
    """``busy`` when a task starts and when the last one ends; ``failed`` with its title and the
    error's message."""

    busy = Signal(bool)
    failed = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._running: Task[Any] | None = None
        self._abandoned = False
        self._relay = _Relay()
        self._relay.ended.connect(self._ended)

    @property
    def running(self) -> Task[Any] | None:
        return self._running

    def holding(self) -> Task[Any] | None:
        """The running task, if it acts: the window does not close while it runs."""
        task = self._running
        return task if task is not None and task.acts else None

    def start(self, task: Task[T]) -> bool:
        """Start ``task``; ``False`` while another runs, or once the tasks are abandoned."""
        if self._running is not None or self._abandoned:
            return False
        self._running = task
        self.busy.emit(True)
        worker = threading.Thread(
            target=_work, args=(self._relay, task), name=f"kresorter: {task.title}", daemon=True
        )
        worker.start()
        return True

    def abandon(self) -> None:
        """The window closes: what still runs is left behind and its result dropped."""
        self._abandoned = True

    def _ended(self, task: Task[Any], outcome: object) -> None:
        if self._abandoned:
            return
        self._running = None
        if isinstance(outcome, _Failed):
            self.failed.emit(task.title, outcome.message)
        else:
            try:
                task.done(outcome)
            except Exception as error:  # applying the result failed: an error as well
                self.failed.emit(task.title, _message(error))
        if self._running is None:  # unless the result started the next task
            self.busy.emit(False)
