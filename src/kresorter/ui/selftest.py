"""``kresorter-ui --self-test REPORT`` (decision 0015, item 17).

The window opens as it always does, shows each page in the sidebar's order, waits while the
page's tasks run and closes; ``REPORT`` then has one line per page and the exit code is 0. The
pages only read: nothing is changed. A failure is its traceback in ``REPORT`` and exit 1: an
error raised while the window opens or reaching the event loop (caught by an ``ErrorHook``,
or raised where the events are processed, as Qt may do), a page whose task ends with an error
(the window's message), or a page still working after ``LIMIT`` seconds, whose task is left
behind. With a standard error, the traceback is written there too, once. As it always does, the
window closes once a task that acts has ended, which the self-test waits for, up to ``LIMIT``.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale

from kresorter.environment import Environment
from kresorter.ui.errors import ErrorHook, Failure, failure
from kresorter.ui.i18n import Translator, language_for
from kresorter.ui.settings import load
from kresorter.ui.window import PAGES, Window

__all__ = ["LIMIT", "PageFailed", "self_test"]

LIMIT = 60.0  # seconds a page may work
PAUSE = 0.01  # between two looks at its tasks


class PageFailed(Exception):
    """A page's task ended with an error: the page's name and the window's message."""


class _Caught(Exception):
    """What the error hook caught: its traceback is the report."""

    def __init__(self, found: Failure) -> None:
        super().__init__(found.message)
        self.found = found


def self_test(application: QCoreApplication, environment: Environment, report: Path) -> int:
    """Open, show and close the window; 0 and a line per page in ``report``, or 1 and the
    traceback of what failed."""
    caught: list[Failure] = []
    previous, sys.excepthook = sys.excepthook, ErrorHook(caught.append)
    try:
        lines = _pages(application, environment, caught)
    except _Caught as stopped:  # the hook wrote it on stderr
        text, code = stopped.found.trace, 1
    except Exception as error:
        text, code = failure(type(error), error, error.__traceback__).trace, 1
        if sys.stderr is not None:
            sys.stderr.write(text)
    else:
        text, code = "".join(f"{line}\n" for line in lines), 0
    finally:
        sys.excepthook = previous
    report.write_text(text, encoding="utf-8")
    return code


def _pages(
    application: QCoreApplication, environment: Environment, caught: list[Failure]
) -> list[str]:
    loaded = load(environment.scan_context())
    translator = Translator(language_for(loaded.settings.language, QLocale.system().name()))
    window = Window(environment, translator, loaded=loaded)
    window.show()
    try:
        lines: list[str] = []
        for name in PAGES:
            window.show_page(name)
            _settle(application, window, name, caught)
            message = window.message.text()
            if message:
                raise PageFailed(f"{name}: {message}")
            lines.append(f"{name}: shown")
        return lines
    finally:
        window.close()
        _closed(application, window)


def _closed(application: QCoreApplication, window: Window) -> None:
    """The window does not close while a task that acts runs, but once it ends: events
    processed until then, up to ``LIMIT`` seconds."""
    deadline = time.monotonic() + LIMIT
    while window.isVisible() and time.monotonic() <= deadline:
        application.processEvents()
        time.sleep(PAUSE)


def _settle(
    application: QCoreApplication, window: Window, name: str, caught: list[Failure]
) -> None:
    """Events processed until no task runs; what the hook caught stops the test."""
    deadline = time.monotonic() + LIMIT
    while True:
        application.processEvents()
        if caught:
            raise _Caught(caught[0])
        if window.tasks.running is None:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"{name}: a task still runs after {LIMIT:g} s")
        time.sleep(PAUSE)
