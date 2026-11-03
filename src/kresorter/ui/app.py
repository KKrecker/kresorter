"""The application and its window (decision 0014); while it runs, an uncaught error is a
dialog (decision 0015, item 25). With a report, the window's self-test instead (item 17)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from kresorter.environment import Environment
from kresorter.ui.errors import ErrorHook, Failure, show_error
from kresorter.ui.i18n import Translator, language_for
from kresorter.ui.selftest import self_test
from kresorter.ui.settings import load
from kresorter.ui.window import Window

__all__ = ["run"]


def run(argv: Sequence[str], environment: Environment, report: Path | None = None) -> int:
    """Show the window in the language of the settings and run until it is closed; with
    ``report``, its self-test."""
    application = QApplication.instance() or QApplication(list(argv))
    if report is not None:
        return self_test(application, environment, report)
    loaded = load(environment.scan_context())
    translator = Translator(language_for(loaded.settings.language, QLocale.system().name()))
    window = Window(environment, translator, loaded=loaded)
    window.show()

    def shown(found: Failure) -> None:
        show_error(window, translator, found)

    previous, sys.excepthook = sys.excepthook, ErrorHook(shown)
    try:
        return application.exec()
    finally:
        sys.excepthook = previous
