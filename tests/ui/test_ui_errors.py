"""An exception that reaches Qt's event loop is shown in a dialog (decision 0015, item 25).

Its type and message, then the traceback in a read-only plain-text box that can be selected
and copied; the window stays open and nothing is sent anywhere. With a standard error, the
traceback is written there too. The hook is the window's only while it runs.
"""

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QWidget
from pytestqt.qtbot import QtBot

from kresorter.environment import Environment
from kresorter.ui import launch
from kresorter.ui.errors import ErrorDialog, ErrorHook, Failure, failure
from kresorter.ui.i18n import Language, Translator
from kresorter.ui.theme import LIGHT, style_sheet
from support.cli import autostart_context, scan_context


def raised() -> Failure:
    try:
        raise RuntimeError("the disk went away")
    except RuntimeError as error:
        return failure(type(error), error, error.__traceback__)


@pytest.fixture
def parent(qtbot: QtBot) -> QWidget:
    widget = QWidget()
    widget.setStyleSheet(style_sheet(LIGHT))
    qtbot.addWidget(widget)
    return widget


def test_a_failure_is_its_type_its_message_and_its_traceback() -> None:
    # [0015.25]
    found = raised()
    assert (found.kind, found.message) == ("RuntimeError", "the disk went away")
    assert found.trace.startswith("Traceback (most recent call last):\n")
    assert found.trace.endswith("RuntimeError: the disk went away\n")


@pytest.mark.parametrize(
    ("language", "title", "close", "copy"),
    [
        ("en", "Kresorter: an unexpected error", "Close", "Copy"),
        ("ru", "Kresorter: непредвиденная ошибка", "Закрыть", "Копировать"),
    ],
)
def test_the_dialog_shows_what_and_where(
    qtbot: QtBot, parent: QWidget, language: Language, title: str, close: str, copy: str
) -> None:
    # [0015.25] in both languages; the traceback read-only, selectable
    found = raised()
    dialog = ErrorDialog(parent, Translator(language), found)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == title
    assert dialog.what.text() == "RuntimeError: the disk went away"
    assert isinstance(dialog.details, QPlainTextEdit)
    assert dialog.details.isReadOnly()
    assert dialog.details.toPlainText() == found.trace
    assert (dialog.close_button.text(), dialog.copy.text()) == (close, copy)
    assert dialog.close_button.isDefault()


def test_copy_puts_the_traceback_on_the_clipboard(qtbot: QtBot, parent: QWidget) -> None:
    # [0015.25]
    found = raised()
    dialog = ErrorDialog(parent, Translator("en"), found)
    qtbot.addWidget(dialog)

    dialog.copy.click()

    assert QApplication.clipboard().text() == found.trace


def test_an_error_without_a_message_is_its_type() -> None:
    # [0015.25]
    dialog = ErrorDialog(None, Translator("en"), Failure("KeyError", "", "Traceback ...\n"))
    assert dialog.what.text() == "KeyError"
    dialog.deleteLater()


def test_the_hook_writes_the_traceback_to_stderr_and_shows_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # [0015.25]
    shown: list[Failure] = []

    ErrorHook(shown.append)(RuntimeError, RuntimeError("the disk went away"), None)

    assert [(f.kind, f.message) for f in shown] == [("RuntimeError", "the disk went away")]
    assert capsys.readouterr().err == "RuntimeError: the disk went away\n"


def test_without_a_standard_error_the_hook_only_shows_it(monkeypatch: pytest.MonkeyPatch) -> None:
    # [0015.25] a GUI program on Windows
    monkeypatch.setattr(sys, "stderr", None)
    shown: list[Failure] = []

    ErrorHook(shown.append)(KeyError, KeyError("x"), None)

    assert [(f.kind, f.message) for f in shown] == [("KeyError", "'x'")]


def test_an_error_in_the_running_window_is_a_dialog_and_the_window_stays_open(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0015.25] through kresorter-ui's main: the hook is installed while the window runs
    environment = Environment(
        scan_context=lambda: scan_context(tmp_path, zone, data_dir),
        autostart_context=lambda: autostart_context("linux", tmp_path),
        llm_env={},
    )
    before = sys.excepthook
    seen: list[tuple[str, bool]] = []

    def boom() -> None:
        raise RuntimeError("a slot failed")

    def inspect() -> None:
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, ErrorDialog):
            QTimer.singleShot(10, inspect)
            return
        windows = [w for w in QApplication.topLevelWidgets() if w.windowTitle() == "Kresorter"]
        seen.append((dialog.what.text(), all(w.isVisible() for w in windows) and bool(windows)))
        dialog.close_button.click()
        QTimer.singleShot(0, close_all)

    def close_all() -> None:
        for window in QApplication.topLevelWidgets():
            window.close()

    QTimer.singleShot(0, boom)
    QTimer.singleShot(0, inspect)

    assert launch.main([], environment=environment) == 0
    assert seen == [("RuntimeError: a slot failed", True)]
    assert "RuntimeError: a slot failed" in capsys.readouterr().err
    assert sys.excepthook is before
