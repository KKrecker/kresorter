"""The window's dialogs: a confirmation before every action and the choice of a folder
(decision 0014, items 38 and 50).

A page never opens a dialog itself: it receives ``Dialogs``, two functions, which the window
binds to the dialogs below and a test answers in their place. A confirmation names its action
and shows what it would do; Cancel is its default button, Escape cancels as well, and only the
action's own button confirms. It is drawn as the prototype's: 520 px wide, the details in a box
on surface that scrolls past eight lines. The folder dialog is the window's own: Qt's file
dialog would keep its state in Qt's settings file (item 35).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileSystemModel,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from safeclean.ui.i18n import Translator
from safeclean.ui.parts import Note, hbox, vbox

__all__ = ["ConfirmDialog", "Confirmation", "Dialogs", "FolderDialog", "choose_folder", "confirm"]


@dataclass(frozen=True)
class Confirmation:
    """What an action asks: ``details`` the paths or items it acts on, ``action`` its button's
    text; ``danger`` for what cannot be undone."""

    title: str
    text: str
    details: tuple[str, ...]
    action: str
    danger: bool = False


@dataclass(frozen=True)
class Dialogs:
    confirm: Callable[[Confirmation], bool]
    choose_folder: Callable[[], Path | None]


WIDTH = 520  # px: the confirmation's width
LINES = 8  # the details shown before they scroll


class ConfirmDialog(QDialog):
    """A confirmation: its title as the ``question`` (semibold, 18 px), its ``text`` in secondary
    text, the ``details`` in a box on surface that scrolls past eight lines (``listed`` holds
    them, a line each), then ``cancel``, bordered and the default button, and the ``action`` as
    the primary button, or the danger one."""

    def __init__(self, parent: QWidget, translator: Translator, confirmation: Confirmation) -> None:
        super().__init__(parent)
        self.setWindowTitle(confirmation.title)
        self.setFixedWidth(WIDTH)
        self.question = QLabel(confirmation.title)
        self.question.setProperty("role", "question")
        self.question.setWordWrap(True)
        self.text = Note(self, confirmation.text, role="secondary")
        self.listed = QLabel("\n".join(confirmation.details))
        self.listed.setWordWrap(True)
        self.listed.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.listed.setContentsMargins(12, 8, 12, 8)
        self.details = QScrollArea()
        self.details.setProperty("role", "details")
        self.details.setFrameShape(QFrame.Shape.NoFrame)
        self.details.setWidgetResizable(True)
        self.details.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details.setWidget(self.listed)
        self.listed.setAutoFillBackground(False)  # the box's surface shows through
        self.details.viewport().setAutoFillBackground(False)
        self.details.setHidden(not confirmation.details)
        self.cancel = QPushButton(translator.text("button.cancel"))
        self.cancel.setDefault(True)
        self.cancel.clicked.connect(self.reject)
        self.action = QPushButton(confirmation.action)
        self.action.setProperty("role", "danger" if confirmation.danger else "primary")
        self.action.setAutoDefault(False)
        self.action.clicked.connect(self.accept)

        buttons = hbox(spacing=8)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.action)
        layout = vbox(self, margins=(24, 24, 24, 24), spacing=12)
        layout.addWidget(self.question)
        layout.addWidget(self.text)
        layout.addSpacing(4)
        layout.addWidget(self.details)
        layout.addSpacing(8)
        layout.addLayout(buttons)
        self.cancel.setFocus()
        if confirmation.details:
            self._fit()

    def _fit(self) -> None:
        """The box as high as its details, up to eight lines."""
        self.ensurePolished()
        self.listed.ensurePolished()
        width = WIDTH - 48
        probe = QLabel("\n".join(["M"] * LINES))
        probe.setWordWrap(True)
        probe.setFont(self.listed.font())
        probe.setContentsMargins(self.listed.contentsMargins())
        most = probe.heightForWidth(width)
        self.details.setFixedHeight(min(self.listed.heightForWidth(width), most))


def confirm(parent: QWidget, translator: Translator, confirmation: Confirmation) -> bool:
    """``True`` only when the action's own button was pressed."""
    dialog = ConfirmDialog(parent, translator, confirmation)
    confirmed = dialog.exec() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    return confirmed


class FolderDialog(QDialog):
    """A folder typed in ``path`` or picked in ``tree``; Add only for an existing folder."""

    def __init__(self, parent: QWidget, translator: Translator, start: Path) -> None:
        super().__init__(parent)
        self.setWindowTitle(translator.text("folder.title"))
        self.path = QLineEdit(str(start))
        self.path.setAccessibleName(translator.text("folder.path"))
        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        self.model.setRootPath("")
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setAccessibleName(translator.text("folder.title"))
        for column in range(1, self.model.columnCount()):
            self.tree.hideColumn(column)
        self.tree.setCurrentIndex(self.model.index(str(start)))
        self.tree.scrollTo(self.tree.currentIndex())
        self.tree.selectionModel().currentChanged.connect(self._picked)
        self.choose = QPushButton(translator.text("folder.choose"))
        self.choose.setProperty("role", "primary")
        self.choose.setDefault(True)
        self.choose.clicked.connect(self.accept)
        cancel = QPushButton(translator.text("button.cancel"))
        cancel.clicked.connect(self.reject)
        self.path.textChanged.connect(self._typed)
        self._typed(self.path.text())

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.choose)
        layout = QVBoxLayout(self)
        layout.addWidget(self.path)
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)
        self.resize(560, 420)

    def _picked(
        self,
        current: QModelIndex | QPersistentModelIndex,
        previous: QModelIndex | QPersistentModelIndex,
    ) -> None:
        self.path.setText(self.model.filePath(current))

    def _typed(self, text: str) -> None:
        folder = Path(text)
        self.choose.setEnabled(folder.is_absolute() and folder.is_dir())


def choose_folder(parent: QWidget, translator: Translator, start: Path) -> Path | None:
    """The folder chosen, or ``None`` when the dialog was cancelled or closed."""
    dialog = FolderDialog(parent, translator, start)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    folder = Path(dialog.path.text()) if accepted else None
    dialog.deleteLater()
    return folder
