"""The window's dialogs: a confirmation before every action and the choice of a folder
(decision 0014, item 38).

A page never opens a dialog itself: it receives ``Dialogs``, two functions, which the window
binds to the dialogs below and a test answers in their place. A confirmation names its action
and shows what it would do; Cancel is its default button, Escape cancels as well, and only the
action's own button confirms. The folder dialog is the window's own: Qt's file dialog would
keep its state in Qt's settings file (item 35).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, QPersistentModelIndex
from PySide6.QtWidgets import (
    QDialog,
    QFileSystemModel,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from safeclean.ui.i18n import Translator

__all__ = ["Confirmation", "Dialogs", "FolderDialog", "choose_folder", "confirm"]


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


def confirm(parent: QWidget, translator: Translator, confirmation: Confirmation) -> bool:
    """``True`` only when the action's own button was pressed."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning if confirmation.danger else QMessageBox.Icon.Question)
    box.setWindowTitle(confirmation.title)
    box.setText(confirmation.text)
    box.setDetailedText("\n".join(confirmation.details))
    action = box.addButton(confirmation.action, QMessageBox.ButtonRole.AcceptRole)
    action.setProperty("role", "danger" if confirmation.danger else "primary")
    cancel = box.addButton(translator.text("button.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    confirmed = box.clickedButton() is action
    box.deleteLater()
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
