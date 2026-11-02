"""The real dialogs, on their own: a page receives them as functions that tests replace
(decision 0014, item 38)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QMessageBox, QWidget
from pytestqt.qtbot import QtBot

from safeclean.ui.dialogs import Confirmation, FolderDialog, choose_folder, confirm
from safeclean.ui.i18n import Translator

MOVE = Confirmation(
    title="Move to quarantine",
    text="Move 2 files (12 B) to the quarantine?",
    details=("/zone/a.pyc", "/zone/b.pyc"),
    action="Move to quarantine",
)


def _once_open(act: Callable[[QWidget], object]) -> None:
    """Act on the modal dialog as soon as it is open."""

    def poll() -> None:
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            QTimer.singleShot(10, poll)
        else:
            act(dialog)

    QTimer.singleShot(0, poll)


def _button(box: QWidget, text: str) -> QAbstractButton:
    assert isinstance(box, QMessageBox)
    [button] = [b for b in box.buttons() if b.text() == text]
    return button


@pytest.fixture
def parent(qtbot: QtBot) -> QWidget:
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


# --- confirming [0014.38] ------------------------------------------------------------------------


def test_the_dialog_names_the_action_and_shows_what_it_will_do(parent: QWidget) -> None:
    # [0014.38]
    seen: dict[str, object] = {}

    def look(box: QWidget) -> None:
        assert isinstance(box, QMessageBox)
        seen["title"] = box.windowTitle()
        seen["text"] = box.text()
        seen["details"] = box.detailedText()
        seen["buttons"] = sorted(b.text() for b in box.buttons() if b.text() != "Show Details...")
        seen["role"] = _button(box, "Move to quarantine").property("role")
        box.reject()

    _once_open(look)
    assert not confirm(parent, Translator("en"), MOVE)
    assert seen == {
        "title": "Move to quarantine",
        "text": "Move 2 files (12 B) to the quarantine?",
        "details": "/zone/a.pyc\n/zone/b.pyc",
        "buttons": ["Cancel", "Move to quarantine"],
        "role": "primary",
    }


def test_the_action_s_button_confirms(parent: QWidget) -> None:
    # [0014.38]
    _once_open(lambda box: _button(box, "Move to quarantine").click())
    assert confirm(parent, Translator("en"), MOVE)


@pytest.mark.parametrize("key", [Qt.Key.Key_Escape, Qt.Key.Key_Return])
def test_escape_and_the_default_button_cancel(parent: QWidget, key: Qt.Key) -> None:
    # [0014.38] Cancel is the default button.
    _once_open(lambda box: QTest.keyClick(box, key))
    assert not confirm(parent, Translator("en"), MOVE)


def test_cancel_and_a_dialog_closed_otherwise_act_on_nothing(parent: QWidget) -> None:
    # [0014.38]
    _once_open(lambda box: _button(box, "Отмена").click())
    assert not confirm(parent, Translator("ru"), MOVE)
    _once_open(lambda box: box.close())
    assert not confirm(parent, Translator("en"), MOVE)


def test_only_a_dangerous_action_is_drawn_as_danger(parent: QWidget) -> None:
    # [0014.38]
    roles: list[object] = []

    def look(box: QWidget) -> None:
        assert isinstance(box, QMessageBox)
        roles.append(_button(box, "Delete permanently").property("role"))
        box.reject()

    _once_open(look)
    purge = Confirmation("Delete", "Delete 1 file?", ("/q/1",), "Delete permanently", danger=True)
    confirm(parent, Translator("en"), purge)
    assert roles == ["danger"]


# --- choosing a folder [0014.38] -----------------------------------------------------------------


def test_the_folder_dialog_starts_where_it_is_told(
    qtbot: QtBot, parent: QWidget, tmp_path: Path
) -> None:
    # [0014.38]
    dialog = FolderDialog(parent, Translator("en"), tmp_path)
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Choose a folder to scan"
    assert dialog.path.text() == str(tmp_path)
    assert dialog.path.accessibleName() == "Folder"
    assert dialog.add.text() == "Add"
    assert dialog.add.isEnabled()


def test_only_an_existing_folder_can_be_added(
    qtbot: QtBot, parent: QWidget, tmp_path: Path
) -> None:
    # [0014.38]
    (tmp_path / "file.txt").write_bytes(b"x")
    dialog = FolderDialog(parent, Translator("en"), tmp_path)
    qtbot.addWidget(dialog)
    dialog.path.setText(str(tmp_path / "missing"))
    assert not dialog.add.isEnabled()
    dialog.path.setText(str(tmp_path / "file.txt"))
    assert not dialog.add.isEnabled()
    dialog.path.setText("")
    assert not dialog.add.isEnabled()
    dialog.path.setText(str(tmp_path))
    assert dialog.add.isEnabled()


def test_a_folder_picked_in_the_tree_is_the_one_added(
    qtbot: QtBot, parent: QWidget, tmp_path: Path
) -> None:
    # [0014.38]
    inner = tmp_path / "inner"
    inner.mkdir()
    dialog = FolderDialog(parent, Translator("en"), tmp_path)
    qtbot.addWidget(dialog)
    dialog.tree.setCurrentIndex(dialog.model.index(str(inner)))
    assert dialog.path.text() == str(inner)


def test_choosing_gives_the_folder_or_nothing(parent: QWidget, tmp_path: Path) -> None:
    # [0014.38]
    inner = tmp_path / "inner"
    inner.mkdir()

    def pick(dialog: QWidget) -> None:
        assert isinstance(dialog, FolderDialog)
        dialog.path.setText(str(inner))
        dialog.add.click()

    _once_open(pick)
    assert choose_folder(parent, Translator("en"), tmp_path) == inner
    _once_open(lambda dialog: QTest.keyClick(dialog, Qt.Key.Key_Escape))
    assert choose_folder(parent, Translator("en"), tmp_path) is None
