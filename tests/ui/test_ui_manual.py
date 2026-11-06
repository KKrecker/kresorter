"""Manual sorting: stage assignments, preview, confirm, and undo."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

import kresorter.ui.manual as manual
from kresorter.llm.group import Grouping
from kresorter.ui.window import Window
from support.files import write
from support.window import FakeDialogs, environment, make_window, wait_idle


def _window(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> tuple[Window, Path, FakeDialogs]:
    folder = zone / "Downloads"
    write(folder / "photo.jpg", b"photo")
    write(folder / "notes.xyz", b"notes")
    write(folder / "other.pdf", b"other")
    dialogs = FakeDialogs(folders=[folder])
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), dialogs=dialogs)
    window.show_page("organize")
    wait_idle(qtbot, window)
    window.organize.choose_button.click()
    wait_idle(qtbot, window)
    return window, folder, dialogs


def test_manual_assign_preview_confirm_and_undo(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    window, folder, dialogs = _window(qtbot, tmp_path, zone, data_dir)
    page = window.organize
    page.manual_button.click()
    editor = page.manual_dialog
    assert editor is not None
    editor.group_name.setText("Trip")
    editor.add_group.click()
    matches = editor.files.findItems("photo.jpg", Qt.MatchFlag.MatchExactly)
    assert len(matches) == 1
    matches[0].setSelected(True)
    editor.assign.click()
    assert editor.assignments == {"photo.jpg": "Trip"}
    assert not (folder / "Trip").exists()
    editor.preview.click()
    wait_idle(qtbot, window)
    assert [(m.source.name, m.category) for m in page._plan.moves] == [("photo.jpg", "Trip")]
    assert not (folder / "Trip").exists()
    page.move_button.click()
    wait_idle(qtbot, window)
    assert dialogs.asked[-1].details == ("photo.jpg → Trip/",)
    assert (folder / "Trip" / "photo.jpg").read_bytes() == b"photo"
    assert (folder / "notes.xyz").read_bytes() == b"notes"
    page.batches.setCurrentItem(page.batch_row(1))
    page.undo_button.click()
    wait_idle(qtbot, window)
    assert (folder / "photo.jpg").read_bytes() == b"photo"


def test_manual_cancel_changes_nothing(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    window, folder, _ = _window(qtbot, tmp_path, zone, data_dir)
    page = window.organize
    page.manual_button.click()
    editor = page.manual_dialog
    assert editor is not None
    editor.group_name.setText("Trip")
    editor.add_group.click()
    editor.cancel.click()
    assert not (folder / "Trip").exists()
    assert {m.source.name for m in page._plan.moves} == {"photo.jpg", "other.pdf"}


def test_editing_groups_search_and_back_to_kind(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    window, _, _ = _window(qtbot, tmp_path, zone, data_dir)
    page = window.organize
    page.manual_button.click()
    editor = page.manual_dialog
    assert editor is not None
    assert not editor.preview.isEnabled()
    editor.group_name.setText("../bad")
    editor.add_group.click()
    assert editor.groups.count() == 0
    assert editor.message.text()
    editor.group_name.setText("Trip")
    editor.add_group.click()
    editor.group_name.setText("trip")
    editor.add_group.click()
    assert editor.groups.count() == 1
    editor.search.setText("photo")
    item = editor.files.findItems("photo.jpg", Qt.MatchFlag.MatchExactly)[0]
    item.setSelected(True)
    editor.assign.click()
    assert editor.assignments == {"photo.jpg": "Trip"}
    editor.clear.click()
    assert editor.assignments == {}
    assert not editor.preview.isEnabled()
    editor.assign.click()
    editor.preview.click()
    wait_idle(qtbot, window)
    page.manual_button.click()
    reopened = page.manual_dialog
    assert reopened is not None
    assert reopened.assignments == {"photo.jpg": "Trip"}
    reopened.cancel.click()
    page.kind_button.click()
    assert {move.source.name for move in page._plan.moves} == {"photo.jpg", "other.pdf"}


def test_manual_plan_detects_changed_folder(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    window, folder, _ = _window(qtbot, tmp_path, zone, data_dir)
    page = window.organize
    page.manual_button.click()
    editor = page.manual_dialog
    assert editor is not None
    editor.group_name.setText("Trip")
    editor.add_group.click()
    editor.files.findItems("photo.jpg", Qt.MatchFlag.MatchExactly)[0].setSelected(True)
    editor.assign.click()
    (folder / "photo.jpg").rename(folder / "renamed.jpg")
    editor.preview.click()
    wait_idle(qtbot, window)
    assert "changed" in page.result.text().lower()
    assert not (folder / "Trip").exists()


def test_manual_ai_is_optional_and_keeps_user_choices(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def suggest(*args: object, **kwargs: object) -> Grouping:
        calls.append(1)
        return Grouping("test", {"photo.jpg": "AI group", "notes.xyz": "AI group"}, (), None)

    monkeypatch.setattr(manual, "group", suggest)
    window, folder, _ = _window(qtbot, tmp_path, zone, data_dir)
    page = window.organize
    page.manual_button.click()
    editor = page.manual_dialog
    assert editor is not None
    assert calls == []
    editor.group_name.setText("Mine")
    editor.add_group.click()
    editor.files.findItems("photo.jpg", Qt.MatchFlag.MatchExactly)[0].setSelected(True)
    editor.assign.click()
    editor.ai.click()
    wait_idle(qtbot, window)
    assert calls == [1]
    assert editor.assignments == {"photo.jpg": "Mine", "notes.xyz": "AI group"}
    assert "may be wrong" in editor.message.text()
    assert not (folder / "Mine").exists()
    editor.cancel.click()


def test_drag_only_accepts_own_file_tiles_on_a_group(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    from typing import cast
    from unittest.mock import MagicMock

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

    window, _, _ = _window(qtbot, tmp_path, zone, data_dir)
    window.organize.manual_button.click()
    editor = window.organize.manual_dialog
    assert editor is not None
    editor.group_name.setText("Group")
    editor.add_group.click()
    editor.files.findItems("photo.jpg", Qt.MatchFlag.MatchExactly)[0].setSelected(True)
    item = editor.groups.item(0)
    point = QPointF(editor.groups.visualItemRect(item).center())
    event = MagicMock()
    event.source.return_value = editor.files
    event.position.return_value = point
    editor.groups.dragEnterEvent(cast(QDragEnterEvent, event))
    editor.groups.dragMoveEvent(cast(QDragMoveEvent, event))
    editor.groups.dropEvent(cast(QDropEvent, event))
    assert editor.assignments == {"photo.jpg": "Group"}
    assert event.acceptProposedAction.call_count == 3
    event.source.return_value = None
    editor.groups.dragEnterEvent(cast(QDragEnterEvent, event))
    editor.groups.dragMoveEvent(cast(QDragMoveEvent, event))
    editor.groups.dropEvent(cast(QDropEvent, event))
    assert event.ignore.call_count == 3
    event.source.return_value = editor.files
    event.position.return_value = QPointF(-100, -100)
    editor.groups.dragMoveEvent(cast(QDragMoveEvent, event))
    editor.groups.dropEvent(cast(QDropEvent, event))
    assert event.ignore.call_count == 5
    editor.cancel.click()


@pytest.mark.parametrize("kind", ["empty", "failed", "partial", "exception"])
def test_manual_ai_failure_is_explained_and_editor_remains_usable(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    from kresorter.llm.failure import ExplanationUnavailable, Unavailable

    def suggest(*args: object, **kwargs: object) -> Grouping:
        if kind == "exception":
            raise RuntimeError("unexpected")
        failure = ExplanationUnavailable(Unavailable.UNREACHABLE, "offline")
        groups = {"photo.jpg": "Trip"} if kind == "partial" else {}
        return Grouping("test", groups, (), None if kind == "empty" else failure)

    monkeypatch.setattr(manual, "group", suggest)
    window, _, _ = _window(qtbot, tmp_path, zone, data_dir)
    window.organize.manual_button.click()
    editor = window.organize.manual_dialog
    assert editor is not None
    editor.ai.click()
    wait_idle(qtbot, window)
    assert editor.ai.isEnabled()
    assert editor.message.text()
    assert bool(editor.assignments) == (kind == "partial")
    editor.cancel.click()


def test_invalid_staged_names_and_no_group_are_ignored(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    window, _, _ = _window(qtbot, tmp_path, zone, data_dir)
    editor = manual.ManualDialog(window, window.organize._plan, {"gone.txt": "Group"})
    qtbot.addWidget(editor)
    assert editor.assignments == {}
    editor._assign()
    assert editor.assignments == {}


def test_ai_busy_does_not_lose_manual_work(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, _, _ = _window(qtbot, tmp_path, zone, data_dir)
    window.organize.manual_button.click()
    editor = window.organize.manual_dialog
    assert editor is not None
    monkeypatch.setattr(window, "run", lambda task: False)
    editor.ai.click()
    assert editor.ai.isEnabled()
    assert not editor.preview.isEnabled()
    editor.cancel.click()


def test_ai_result_after_cancel_is_not_applied(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    started, release = threading.Event(), threading.Event()

    def slow(*args: object, **kwargs: object) -> Grouping:
        started.set()
        release.wait(5)
        return Grouping("test", {"photo.jpg": "Trip"}, (), None)

    monkeypatch.setattr(manual, "group", slow)
    window, _, _ = _window(qtbot, tmp_path, zone, data_dir)
    window.organize.manual_button.click()
    editor = window.organize.manual_dialog
    assert editor is not None
    editor.ai.click()
    qtbot.waitUntil(started.is_set)
    editor.cancel.click()
    release.set()
    wait_idle(qtbot, window)
    assert editor.assignments == {}


def test_manual_preview_rejects_folder_changed_into_project(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    window, folder, _ = _window(qtbot, tmp_path, zone, data_dir)
    page = window.organize
    page.manual_button.click()
    editor = page.manual_dialog
    assert editor is not None
    editor.group_name.setText("Trip")
    editor.add_group.click()
    editor.files.findItems("photo.jpg", Qt.MatchFlag.MatchExactly)[0].setSelected(True)
    editor.assign.click()
    write(folder / "Makefile")
    editor.preview.click()
    wait_idle(qtbot, window)
    assert "project" in page.summary.text().lower()
    assert not (folder / "Trip").exists()


def test_manual_ai_sends_only_file_names_on_request(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    import json

    from kresorter.llm.settings import URL_VARIABLE
    from support.ollama import TAGS, VERSION, ScriptedOllama, generated

    folder = zone / "Downloads"
    write(folder / "photo1.jpg", b"secret one")
    write(folder / "photo2.jpg", b"secret two")
    answer = generated(json.dumps({"groups": [{"folder": "Trip", "files": [1, 2]}]}))
    with ScriptedOllama(VERSION, TAGS, answer) as ollama:
        dialogs = FakeDialogs(folders=[folder])
        env = environment(tmp_path, zone, data_dir, llm_env={URL_VARIABLE: ollama.address.url})
        window = make_window(qtbot, env, dialogs=dialogs)
        window.show_page("organize")
        wait_idle(qtbot, window)
        window.organize.choose_button.click()
        wait_idle(qtbot, window)
        window.organize.manual_button.click()
        editor = window.organize.manual_dialog
        assert editor is not None
        assert ollama.connections == 0
        editor.ai.click()
        wait_idle(qtbot, window)
        assert editor.assignments == {"photo1.jpg": "Trip", "photo2.jpg": "Trip"}
        request = ollama.received[-1].body.decode("utf-8")
        assert "photo1.jpg" in request
        assert str(folder) not in request
        assert "secret one" not in request
        editor.cancel.click()
