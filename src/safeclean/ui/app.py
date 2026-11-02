"""The application and its window (decision 0014)."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from safeclean.environment import Environment
from safeclean.ui.i18n import Translator, language_for
from safeclean.ui.settings import load
from safeclean.ui.window import Window

__all__ = ["run"]


def run(argv: Sequence[str], environment: Environment) -> int:
    """Show the window in the language of the settings and run until it is closed."""
    application = QApplication.instance() or QApplication(list(argv))
    settings = load(environment.scan_context()).settings
    translator = Translator(language_for(settings.language, QLocale.system().name()))
    window = Window(environment, translator)
    window.show()
    return application.exec()
