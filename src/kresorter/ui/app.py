"""The application and its window (decision 0014)."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from kresorter.environment import Environment
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
    return application.exec()
