"""The application and its window (decision 0014); while it runs, an uncaught error is a
dialog (decision 0015, item 25)."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from kresorter.environment import Environment
from kresorter.ui.errors import ErrorHook, Failure, show_error
from kresorter.ui.i18n import Translator, language_for
from kresorter.ui.settings import load
from kresorter.ui.window import Window

__all__ = ["run"]


def run(argv: Sequence[str], environment: Environment) -> int:
    """Show the window in the language of the settings and run until it is closed."""
    application = QApplication.instance() or QApplication(list(argv))
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
