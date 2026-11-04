"""The window's restart, in the same process: ``ui.app.run`` opens the window again once a
restart closed it, with the settings read again, on the same page; a window closed otherwise
ends the application (decision 0018, items 3 and 4)."""

from collections.abc import Callable
from pathlib import Path

import shiboken6
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from kresorter.ui.app import run
from kresorter.ui.dialogs import ConfirmDialog
from kresorter.ui.settings import Settings
from kresorter.ui.window import PAGES, Window
from support.window import environment


def _shown() -> list[Window]:
    return [w for w in QApplication.topLevelWidgets() if isinstance(w, Window) and w.isVisible()]


def _when(found: Callable[[], object], then: Callable[[object], None], tries: int = 500) -> None:
    """``then`` with what ``found`` returns, once it returns something; after ``tries`` looks
    (five seconds), every window is closed instead, which ends the run."""
    what = found()
    if what is not None:
        then(what)
    elif tries:
        QTimer.singleShot(10, lambda: _when(found, then, tries - 1))
    else:
        for widget in QApplication.topLevelWidgets():
            widget.close()


def _state(window: Window) -> tuple[str, str, Settings]:
    """The window's language (its first page's name), its page and its settings."""
    return (
        window.sidebar.item(0).text(),
        PAGES[window.sidebar.currentRow()],
        window.settings.current,
    )


def test_restart_now_opens_the_window_again_in_the_new_language_on_the_same_page(
    qapp: QApplication, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.3] [0018.4] No program is launched: the same process, the same application.
    seen: list[object] = []
    opened: list[Window] = []

    def first() -> Window | None:
        return next(iter(_shown()), None)

    def again() -> Window | None:
        return next((w for w in _shown() if w not in opened), None)

    def dialog() -> ConfirmDialog | None:
        modal = QApplication.activeModalWidget()
        return modal if isinstance(modal, ConfirmDialog) else None

    def change(window: object) -> None:
        assert isinstance(window, Window)
        opened.append(window)
        seen.append(_state(window))
        window.show_page("settings")
        _when(dialog, answer)
        window.settings.language.setCurrentIndex(2)  # until the confirmation is answered
        _when(again, reopened)

    def answer(asked: object) -> None:
        assert isinstance(asked, ConfirmDialog)
        seen.append((asked.question.text(), asked.action.text()))
        asked.action.click()

    def reopened(window: object) -> None:
        assert isinstance(window, Window)
        seen.append(_state(window))
        window.close()

    _when(first, change)
    assert run([], environment(tmp_path, zone, data_dir)) == 0
    assert seen == [
        ("Overview", "overview", Settings()),
        ("Restart the window?", "Restart now"),
        ("Обзор", "settings", Settings(language="ru")),
    ]
    assert not shiboken6.isValid(opened[0])  # the window closed is gone


def test_a_window_closed_otherwise_ends_the_application(
    qapp: QApplication, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.4]
    opened: list[Window] = []

    def close(window: object) -> None:
        assert isinstance(window, Window)
        opened.append(window)
        window.close()

    _when(lambda: next(iter(_shown()), None), close)
    assert run([], environment(tmp_path, zone, data_dir)) == 0
    assert len(opened) == 1
    assert _shown() == []
