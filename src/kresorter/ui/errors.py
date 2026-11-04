"""An exception that reaches Qt's event loop is shown in a dialog (decision 0015, item 25).

While the window runs, ``ErrorHook`` is ``sys.excepthook``, which PySide6 calls for an
exception a slot or a virtual method raises: the traceback goes to stderr when there is one,
then ``ErrorDialog`` shows the exception's type and message and, in a read-only plain-text box,
the traceback, which Copy puts on the clipboard. The window stays open; nothing is sent
anywhere.
"""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFrame, QPlainTextEdit, QPushButton, QWidget

from kresorter.ui.i18n import Translator
from kresorter.ui.parts import Label, Note, hbox, vbox

__all__ = ["ErrorDialog", "ErrorHook", "Failure", "failure", "show_error"]

WIDTH = 640  # px: a traceback's lines are long
_PADDING = (12, 8, 12, 8)  # px: around the traceback, inside its box


@dataclass(frozen=True)
class Failure:
    kind: str  # the exception's type, by name
    message: str
    trace: str  # the traceback, as Python prints it


def failure(
    kind: type[BaseException], error: BaseException, trace: TracebackType | None
) -> Failure:
    return Failure(
        kind.__name__, str(error), "".join(traceback.format_exception(kind, error, trace))
    )


class ErrorHook:
    """``sys.excepthook`` while the window runs: stderr when there is one, then ``show``."""

    def __init__(self, show: Callable[[Failure], None]) -> None:
        self.show = show

    def __call__(
        self, kind: type[BaseException], error: BaseException, trace: TracebackType | None
    ) -> None:
        found = failure(kind, error, trace)
        if sys.stderr is not None:
            sys.stderr.write(found.trace)
        self.show(found)


class ErrorDialog(QDialog):
    """The title as the ``question``, what the window does now in secondary text, the type and
    message, the traceback in a box on surface, then Copy and Close, the default button."""

    def __init__(self, parent: QWidget | None, translator: Translator, found: Failure) -> None:
        super().__init__(parent)
        title = translator.text("error.title")
        self.setWindowTitle(title)
        self.setFixedWidth(WIDTH)
        self.question = Label(title)
        self.question.setProperty("role", "question")
        self.text = Note(self, translator.text("error.text"), role="secondary")
        self.what = Label(f"{found.kind}: {found.message}" if found.message else found.kind)
        self.what.setWordWrap(True)
        self.what.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details = QPlainTextEdit()
        self.details.setProperty("role", "details")
        self.details.setReadOnly(True)
        self.details.setFrameShape(QFrame.Shape.NoFrame)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.details.setViewportMargins(*_PADDING)
        self.details.document().setDocumentMargin(0)
        self.details.viewport().setAutoFillBackground(False)  # the box's surface shows through
        self.details.setPlainText(found.trace)
        self.copy = QPushButton(translator.text("button.copy"))
        self.copy.setAutoDefault(False)
        self.copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(found.trace))
        self.close_button = QPushButton(translator.text("button.close"))
        self.close_button.setProperty("role", "primary")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)

        buttons = hbox(spacing=8)
        buttons.addStretch(1)
        buttons.addWidget(self.copy)
        buttons.addWidget(self.close_button)
        layout = vbox(self, margins=(24, 24, 24, 24), spacing=12)
        layout.addWidget(self.question)
        layout.addWidget(self.text)
        layout.addWidget(self.what)
        layout.addWidget(self.details, 1)
        layout.addSpacing(8)
        layout.addLayout(buttons)
        self.close_button.setFocus()


def show_error(parent: QWidget, translator: Translator, found: Failure) -> None:
    """The dialog over ``parent``, until it is closed."""
    dialog = ErrorDialog(parent, translator, found)
    dialog.exec()
    dialog.deleteLater()
