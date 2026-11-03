"""Tasks run in a worker thread, one at a time; closing waits only for what acts (decision 0014,
items 15-17)."""

import sqlite3
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from pytestqt.qtbot import QtBot

from kresorter.storage.session import SessionFailed, run_session
from kresorter.ui.tasks import Task, Tasks
from support.cli import scan_context


def _nothing(result: object) -> None:
    return None


def _waiting(release: threading.Event) -> Task[bool]:
    return Task("Waiting", lambda: release.wait(timeout=10), _nothing)


# --- off the window's thread [0014.15] -----------------------------------------------------------


def test_the_work_runs_in_a_worker_and_its_result_in_the_window_s_thread(qtbot: QtBot) -> None:
    # [0014.15]
    tasks = Tasks()
    seen: dict[str, int] = {}

    def work() -> int:
        seen["work"] = threading.get_ident()
        return 42

    def done(result: int) -> None:
        seen["done"] = threading.get_ident()
        seen["result"] = result

    assert tasks.start(Task("Counting", work, done))
    qtbot.waitUntil(lambda: "done" in seen)
    assert seen["work"] != threading.get_ident()
    assert seen["done"] == threading.get_ident()
    assert seen["result"] == 42


def test_the_window_keeps_handling_events_while_a_task_runs(qtbot: QtBot) -> None:
    # [0014.15] The work waits for a timer of the window's thread: were that thread blocked, the
    # work would never end.
    tasks = Tasks()
    release = threading.Event()
    results: list[bool] = []
    assert tasks.start(Task("Waiting", lambda: release.wait(timeout=10), results.append))
    QTimer.singleShot(50, release.set)
    qtbot.waitUntil(lambda: results == [True], timeout=5000)


def test_a_journal_session_is_opened_used_and_closed_in_the_worker(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.15]
    context = scan_context(tmp_path, zone, data_dir)
    used: list[int] = []

    def body(conn: sqlite3.Connection, where: Path) -> sqlite3.Connection:
        conn.execute("SELECT count(*) FROM operations").fetchone()
        used.append(threading.get_ident())
        return conn

    tasks = Tasks()
    results: list[sqlite3.Connection | SessionFailed] = []
    session = Task("Journal", lambda: run_session(context, body), results.append, acts=True)
    assert tasks.start(session)
    qtbot.waitUntil(lambda: bool(results))
    conn = results[0]
    assert isinstance(conn, sqlite3.Connection)
    assert used != [threading.get_ident()]
    assert len(used) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="thread"):
        conn.execute("SELECT 1")


# --- one task at a time [0014.16] ----------------------------------------------------------------


def test_one_task_at_a_time(qtbot: QtBot) -> None:
    # [0014.16]
    tasks = Tasks()
    busy: list[bool] = []
    tasks.busy.connect(busy.append)
    release = threading.Event()
    first = _waiting(release)
    assert tasks.running is None
    assert tasks.start(first)
    assert tasks.running is first
    assert busy == [True]
    ran: list[str] = []
    assert not tasks.start(Task("Second", lambda: ran.append("second"), _nothing))
    release.set()
    qtbot.waitUntil(lambda: tasks.running is None)
    assert busy == [True, False]
    assert ran == []
    assert tasks.start(Task("Second", lambda: ran.append("second"), _nothing))
    qtbot.waitUntil(lambda: tasks.running is None)
    assert ran == ["second"]
    assert busy == [True, False, True, False]


def test_a_task_started_by_the_end_of_another_runs(qtbot: QtBot) -> None:
    # [0014.16] When a task ends the next may start at once, from its result.
    tasks = Tasks()
    results: list[str] = []
    second = Task("Second", lambda: "second", results.append)

    def then(result: str) -> None:
        results.append(result)
        assert tasks.start(second)

    assert tasks.start(Task("First", lambda: "first", then))
    qtbot.waitUntil(lambda: results == ["first", "second"])
    assert tasks.running is None


def _raise(error: Exception) -> None:
    raise error


@pytest.mark.parametrize(
    ("error", "message"),
    [(OSError("disk on fire"), "disk on fire"), (RuntimeError(), "RuntimeError")],
)
def test_an_exception_in_a_task_is_an_error_with_its_message(
    qtbot: QtBot, error: Exception, message: str
) -> None:
    # [0014.16] And the next task runs as if nothing happened.
    tasks = Tasks()
    failures: list[tuple[str, str]] = []
    tasks.failed.connect(lambda title, text: failures.append((title, text)))
    called: list[object] = []
    assert tasks.start(Task("Burning", lambda: _raise(error), called.append))
    qtbot.waitUntil(lambda: bool(failures))
    assert failures == [("Burning", message)]
    assert called == []
    assert tasks.running is None
    assert tasks.start(Task("Next", lambda: "next", called.append))
    qtbot.waitUntil(lambda: called == ["next"])


def test_an_exception_where_the_result_is_applied_is_an_error_too(qtbot: QtBot) -> None:
    # [0014.16]
    tasks = Tasks()
    failures: list[tuple[str, str]] = []
    tasks.failed.connect(lambda title, text: failures.append((title, text)))
    assert tasks.start(Task("Showing", lambda: 1, lambda _: _raise(ValueError("no room"))))
    qtbot.waitUntil(lambda: bool(failures))
    assert failures == [("Showing", "no room")]
    assert tasks.running is None


# --- closing waits for what acts [0014.17] -------------------------------------------------------


def test_only_a_task_that_acts_holds_the_window(qtbot: QtBot) -> None:
    # [0014.17]
    tasks = Tasks()
    assert tasks.holding() is None
    release = threading.Event()
    assert tasks.start(_waiting(release))
    assert tasks.holding() is None
    release.set()
    qtbot.waitUntil(lambda: tasks.running is None)
    acting = Task("Moving", lambda: release.wait(timeout=10), _nothing, acts=True)
    release.clear()
    assert tasks.start(acting)
    assert tasks.holding() is acting
    release.set()
    qtbot.waitUntil(lambda: tasks.running is None)
    assert tasks.holding() is None


def test_an_abandoned_task_is_left_behind_and_its_result_dropped(qtbot: QtBot) -> None:
    # [0014.17]
    tasks = Tasks()
    busy: list[bool] = []
    tasks.busy.connect(busy.append)
    release = threading.Event()
    ended = threading.Event()
    results: list[bool] = []

    def work() -> bool:
        try:
            return release.wait(timeout=10)
        finally:
            ended.set()

    assert tasks.start(Task("Scanning", work, results.append))
    tasks.abandon()
    release.set()
    assert ended.wait(timeout=10)
    qtbot.wait(100)
    assert results == []
    assert busy == [True]
    assert not tasks.start(Task("After", lambda: True, results.append))
