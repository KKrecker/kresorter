"""The window opens and closes without a display (decision 0014, item 40)."""

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from kresorter.environment import Environment
from kresorter.ui import launch
from support.cli import autostart_context, scan_context


def test_main_opens_the_window_and_returns_0_once_it_is_closed(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.40]
    environment = Environment(
        scan_context=lambda: scan_context(tmp_path, zone, data_dir),
        autostart_context=lambda: autostart_context("linux", tmp_path),
        llm_env={},
    )
    shown: list[str] = []

    def close() -> None:
        windows = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
        shown.extend(w.windowTitle() for w in windows)
        for window in windows:
            window.close()

    QTimer.singleShot(0, close)

    assert launch.main([], environment=environment) == 0
    assert shown == ["Kresorter"]
    assert [
        w for w in QApplication.topLevelWidgets() if isinstance(w, QWidget) and w.isVisible()
    ] == []
