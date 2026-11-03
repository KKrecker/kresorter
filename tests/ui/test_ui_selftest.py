"""``kresorter-ui --self-test REPORT`` (decision 0015, item 17).

The window opens, shows each page in the sidebar's order and closes; ``REPORT`` has one line
per page and the exit code is 0: the user's files are as they were, and no setting is saved
(the pages' sessions make the data directory and its journal, as when they are opened). A
failure is its traceback in ``REPORT``
and exit 1: an error while the window opens or in a slot, a page whose task ends with an error,
a page still working after the limit.
"""

import sys
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from kresorter.autostart.listing import AutostartContext, list_autostart
from kresorter.autostart.models import AutostartListing
from kresorter.core.scanner import ScanContext
from kresorter.environment import Environment
from kresorter.ui import autostart, launch, selftest
from kresorter.ui.window import PAGES, Window
from support.cli import autostart_context, scan_context
from support.files import snapshot

pytestmark = pytest.mark.usefixtures("qtbot")


def made(tmp_path: Path, zone: Path, data_dir: Path) -> Environment:
    return Environment(
        scan_context=lambda: scan_context(tmp_path, zone, data_dir),
        autostart_context=lambda: autostart_context("linux", tmp_path),
        llm_env={},
    )


def visible() -> list[QWidget]:
    """The windows still open: other tests' widgets are not this one's."""
    return [w for w in QApplication.topLevelWidgets() if isinstance(w, Window) and w.isVisible()]


def self_test(report: Path, environment: Environment) -> int:
    return launch.main(["--self-test", str(report)], environment=environment)


def test_each_page_is_shown_and_has_its_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0015.17] in the sidebar's order, then the window is closed; nothing is changed
    (zone / "old.log").write_text("junk", encoding="utf-8")
    shown: list[str] = []
    show_page = Window.show_page

    def showing(window: Window, name: str) -> None:
        shown.append(name)
        show_page(window, name)

    monkeypatch.setattr(Window, "show_page", showing)
    report = tmp_path / "out" / "report.txt"
    report.parent.mkdir()
    before, hook = snapshot(tmp_path / "zone"), sys.excepthook

    assert self_test(report, made(tmp_path, zone, data_dir)) == 0

    assert report.read_text(encoding="utf-8") == "".join(f"{name}: shown\n" for name in PAGES)
    assert shown == list(PAGES)
    assert visible() == []
    assert snapshot(tmp_path / "zone") == before
    assert not (data_dir / "settings.json").exists()
    assert sys.excepthook is hook


def test_an_error_while_the_window_opens_is_its_traceback(tmp_path: Path) -> None:
    # [0015.17]
    def broken() -> ScanContext:
        raise RuntimeError("no context")

    report = tmp_path / "report.txt"
    hook = sys.excepthook

    assert self_test(report, Environment(scan_context=broken, llm_env={})) == 1

    text = report.read_text(encoding="utf-8")
    assert text.startswith("Traceback (most recent call last):\n")
    assert text.endswith("RuntimeError: no context\n")
    assert sys.excepthook is hook


def test_an_error_in_a_slot_is_its_traceback(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0015.17] the window is closed; with a standard error the traceback is there too
    def boom() -> None:
        raise RuntimeError("a slot failed")

    QTimer.singleShot(0, boom)
    report = tmp_path / "report.txt"
    hook = sys.excepthook

    assert self_test(report, made(tmp_path, zone, data_dir)) == 1

    text = report.read_text(encoding="utf-8")
    assert text.startswith("Traceback (most recent call last):\n")
    assert text.endswith("RuntimeError: a slot failed\n")
    assert "RuntimeError: a slot failed" in capsys.readouterr().err
    assert visible() == []
    assert sys.excepthook is hook


def test_a_page_whose_task_fails_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0015.17] the window shows the task's error as a message; the self-test stops on it
    def broken(context: AutostartContext, *, include_machine: bool) -> AutostartListing:
        raise RuntimeError("no autostart")

    monkeypatch.setattr(autostart, "list_autostart", broken)
    report = tmp_path / "report.txt"

    assert self_test(report, made(tmp_path, zone, data_dir)) == 1

    last = report.read_text(encoding="utf-8").splitlines()[-1]
    assert last.startswith("kresorter.ui.selftest.PageFailed: autostart: ")
    assert last.endswith("no autostart")
    assert visible() == []


def test_a_page_still_working_after_the_limit_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0015.17] 60 seconds, made shorter here; what still runs is left behind
    monkeypatch.setattr(selftest, "LIMIT", 0.05)
    release = threading.Event()

    def slow(context: AutostartContext, *, include_machine: bool) -> AutostartListing:
        release.wait(10)
        return list_autostart(context, include_machine=include_machine)

    monkeypatch.setattr(autostart, "list_autostart", slow)
    report = tmp_path / "report.txt"
    try:
        assert self_test(report, made(tmp_path, zone, data_dir)) == 1
    finally:
        release.set()

    last = report.read_text(encoding="utf-8").splitlines()[-1]
    assert last == "TimeoutError: autostart: a task still runs after 0.05 s"
    assert visible() == []


def test_the_limit_is_a_minute() -> None:
    # [0015.17]
    assert selftest.LIMIT == 60.0
