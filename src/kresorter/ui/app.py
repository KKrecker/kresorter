"""The application and its window (decision 0014); while it runs, an uncaught error is a
dialog (decision 0015, item 25). With a report, the window's self-test instead (item 17). A
restart closes the window and opens it again, in the same process, with the settings read again,
on the same page; a window closed otherwise ends the application (decision 0018, item 4)."""

from __future__ import annotations

import functools
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from kresorter.environment import Environment
from kresorter.ui.errors import ErrorHook, show_error
from kresorter.ui.i18n import Translator, language_for
from kresorter.ui.selftest import self_test
from kresorter.ui.settings import load
from kresorter.ui.window import PAGES, Window

__all__ = ["run"]


def run(argv: Sequence[str], environment: Environment, report: Path | None = None) -> int:
    """Show the window in the language of the settings and run until it is closed, opening it
    again after each restart; with ``report``, its self-test."""
    application = QApplication.instance() or QApplication(list(argv))
    if report is not None:
        return self_test(application, environment, report)
    previous = sys.excepthook
    page = PAGES[0]
    try:
        while True:
            window = _open(environment, page)
            code = application.exec()
            window.deleteLater()  # once the next window's loop starts
            if window.restart_page is None:
                return code
            page = window.restart_page
    finally:
        sys.excepthook = previous


def _open(environment: Environment, page: str) -> Window:
    """The window on ``page``, an uncaught error shown over it."""
    loaded = load(environment.scan_context())
    translator = Translator(language_for(loaded.settings.language, QLocale.system().name()))
    window = Window(environment, translator, loaded=loaded)
    window.show_page(page)
    window.show()
    sys.excepthook = ErrorHook(functools.partial(show_error, window, translator))
    return window
