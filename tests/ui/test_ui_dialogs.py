"""The real dialogs, on their own: a page receives them as functions that tests replace
(decision 0014, items 38 and 50)."""

import itertools
from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from safeclean.ui.dialogs import Confirmation, ConfirmDialog, FolderDialog, choose_folder, confirm
from safeclean.ui.i18n import Translator
from safeclean.ui.theme import LIGHT, style_sheet

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


def _once_asked(act: Callable[[ConfirmDialog], object]) -> None:
    """Act on the confirmation as soon as it is open."""

    def checked(dialog: QWidget) -> None:
        assert isinstance(dialog, ConfirmDialog)
        act(dialog)

    _once_open(checked)


@pytest.fixture
def parent(qtbot: QtBot) -> QWidget:
    """A parent with the window's style sheet, which its dialogs take."""
    widget = QWidget()
    widget.setStyleSheet(style_sheet(LIGHT))
    qtbot.addWidget(widget)
    return widget


def _shown(qtbot: QtBot, parent: QWidget, confirmation: Confirmation) -> ConfirmDialog:
    dialog = ConfirmDialog(parent, Translator("en"), confirmation)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    return dialog


def _paths(count: int) -> Confirmation:
    return Confirmation("Restore", "Restore?", tuple(f"/q/{n}" for n in range(count)), "Restore")


# --- confirming [0014.38] [0014.50] --------------------------------------------------------------


def test_the_dialog_names_the_action_and_shows_what_it_will_do(parent: QWidget) -> None:
    # [0014.38] [0014.50]
    seen: dict[str, object] = {}

    def look(dialog: ConfirmDialog) -> None:
        seen["title"] = dialog.windowTitle()
        seen["question"] = dialog.question.text()
        seen["text"] = dialog.text.text()
        seen["details"] = dialog.listed.text()
        seen["buttons"] = [dialog.cancel.text(), dialog.action.text()]
        seen["role"] = dialog.action.property("role")
        dialog.reject()

    _once_asked(look)
    assert not confirm(parent, Translator("en"), MOVE)
    assert seen == {
        "title": "Move to quarantine",
        "question": "Move to quarantine",
        "text": "Move 2 files (12 B) to the quarantine?",
        "details": "/zone/a.pyc\n/zone/b.pyc",
        "buttons": ["Cancel", "Move to quarantine"],
        "role": "primary",
    }


def test_the_action_s_button_confirms(parent: QWidget) -> None:
    # [0014.38]
    _once_asked(lambda dialog: dialog.action.click())
    assert confirm(parent, Translator("en"), MOVE)


@pytest.mark.parametrize("key", [Qt.Key.Key_Escape, Qt.Key.Key_Return])
def test_escape_and_the_default_button_cancel(parent: QWidget, key: Qt.Key) -> None:
    # [0014.3] [0014.38] [0014.50] Cancel is the default button.
    _once_asked(lambda dialog: QTest.keyClick(dialog, key))
    assert not confirm(parent, Translator("en"), MOVE)


def test_cancel_and_a_dialog_closed_otherwise_act_on_nothing(parent: QWidget) -> None:
    # [0014.3] [0014.38]
    def cancel(dialog: ConfirmDialog) -> None:
        assert dialog.cancel.text() == "Отмена"
        dialog.cancel.click()

    _once_asked(cancel)
    assert not confirm(parent, Translator("ru"), MOVE)
    _once_asked(lambda dialog: dialog.close())
    assert not confirm(parent, Translator("en"), MOVE)


def test_only_a_dangerous_action_is_drawn_as_danger(parent: QWidget) -> None:
    # [0014.38] [0014.50]
    roles: list[object] = []

    def look(dialog: ConfirmDialog) -> None:
        roles.append(dialog.action.property("role"))
        dialog.reject()

    _once_asked(look)
    purge = Confirmation("Delete", "Delete 1 file?", ("/q/1",), "Delete permanently", danger=True)
    confirm(parent, Translator("en"), purge)
    assert roles == ["danger"]


def test_the_dialog_is_520_px_wide_its_title_semibold_its_question_secondary(
    qtbot: QtBot, parent: QWidget
) -> None:
    # [0014.50]
    dialog = _shown(qtbot, parent, MOVE)
    assert dialog.width() == 520
    assert dialog.question.property("role") == "question"
    assert dialog.question.font().pixelSize() == 18
    assert dialog.question.font().weight() == QFont.Weight.DemiBold
    assert dialog.text.property("role") == "secondary"
    assert dialog.details.property("role") == "details"
    assert dialog.cancel.isDefault()
    assert not dialog.cancel.property("role")  # bordered, as every button that is not primary
    assert dialog.focusWidget() is dialog.cancel
    layout = dialog.layout()
    assert layout is not None
    margins = layout.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (24, 24, 24, 24)


def test_the_parts_come_one_under_the_other_and_the_buttons_at_the_right(
    qtbot: QtBot, parent: QWidget
) -> None:
    # [0014.50]
    dialog = _shown(qtbot, parent, MOVE)
    parts = [dialog.question, dialog.text, dialog.details, dialog.cancel]
    for upper, lower in itertools.pairwise(parts):
        assert upper.geometry().bottom() < lower.geometry().top()
    assert dialog.cancel.geometry().right() < dialog.action.geometry().left()
    assert dialog.cancel.geometry().top() == dialog.action.geometry().top()
    assert dialog.action.geometry().right() == dialog.width() - 24 - 1
    assert dialog.details.geometry().left() == 24
    assert dialog.details.geometry().right() == dialog.width() - 24 - 1


def test_the_details_scroll_past_eight_lines(qtbot: QtBot, parent: QWidget) -> None:
    # [0014.50]
    two, eight, nine = (_shown(qtbot, parent, _paths(count)) for count in (2, 8, 9))
    assert two.details.height() < eight.details.height() == nine.details.height()
    assert two.details.verticalScrollBar().maximum() == 0
    assert eight.details.verticalScrollBar().maximum() == 0
    assert nine.details.verticalScrollBar().maximum() > 0


def test_a_long_path_wraps_instead_of_widening_the_dialog(qtbot: QtBot, parent: QWidget) -> None:
    # [0014.50]
    long = "/" + "/".join(["folder"] * 30) + "/file.txt"
    dialog = _shown(qtbot, parent, Confirmation("Restore", "Restore?", (long,), "Restore"))
    assert dialog.width() == 520
    assert dialog.listed.text() == long
    assert dialog.details.height() > _shown(qtbot, parent, _paths(1)).details.height()


def test_without_details_the_box_takes_no_room(qtbot: QtBot, parent: QWidget) -> None:
    # [0014.47] [0014.50]
    dialog = _shown(qtbot, parent, Confirmation("Turn on", "Turn it on?", (), "Turn on"))
    assert not dialog.details.isVisible()
    assert dialog.text.geometry().bottom() < dialog.cancel.geometry().top()


# --- choosing a folder [0014.38] -----------------------------------------------------------------


def test_the_folder_dialog_starts_where_it_is_told(
    qtbot: QtBot, parent: QWidget, tmp_path: Path
) -> None:
    # [0014.38]
    dialog = FolderDialog(parent, Translator("en"), tmp_path)
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Choose a folder"
    assert dialog.path.text() == str(tmp_path)
    assert dialog.path.accessibleName() == "Folder"
    assert dialog.choose.text() == "Choose"
    assert dialog.choose.isEnabled()


def test_only_an_existing_folder_can_be_chosen(
    qtbot: QtBot, parent: QWidget, tmp_path: Path
) -> None:
    # [0014.38]
    (tmp_path / "file.txt").write_bytes(b"x")
    dialog = FolderDialog(parent, Translator("en"), tmp_path)
    qtbot.addWidget(dialog)
    dialog.path.setText(str(tmp_path / "missing"))
    assert not dialog.choose.isEnabled()
    dialog.path.setText(str(tmp_path / "file.txt"))
    assert not dialog.choose.isEnabled()
    dialog.path.setText("")
    assert not dialog.choose.isEnabled()
    dialog.path.setText(str(tmp_path))
    assert dialog.choose.isEnabled()


def test_a_folder_picked_in_the_tree_is_the_one_chosen(
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
        dialog.choose.click()

    _once_open(pick)
    assert choose_folder(parent, Translator("en"), tmp_path) == inner
    _once_open(lambda dialog: QTest.keyClick(dialog, Qt.Key.Key_Escape))
    assert choose_folder(parent, Translator("en"), tmp_path) is None
