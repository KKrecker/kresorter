"""The application and its window (decision 0014)."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QApplication, QMainWindow

from safeclean.environment import Environment

__all__ = ["run"]

TITLE = "safeclean"


def run(argv: Sequence[str], environment: Environment) -> int:
    """Show the window and run until it is closed."""
    application = QApplication.instance() or QApplication(list(argv))
    window = QMainWindow()
    window.setWindowTitle(TITLE)
    window.show()
    return application.exec()
