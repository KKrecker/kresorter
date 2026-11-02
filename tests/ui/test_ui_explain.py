"""Explanations, on request: the detail of a finding, an autostart entry and a file organize
leaves in place has Explain (local AI). It asks for the one subject of that result through
``llm.explain`` and shows the answer under a label that names the model and says it may be
wrong, or why there is none, in the window's words (decision 0014, item 26). Nothing is asked
without the button, nothing is stored, and an answer changes no level, selection, plan or
action."""

import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
from pytestqt.qtbot import QtBot

from safeclean.analysis.report import Finding
from safeclean.llm.settings import URL_VARIABLE, Address
from safeclean.llm.subjects import Result, subject_of
from safeclean.ui.i18n import Language
from safeclean.ui.window import Window
from support.files import write
from support.interrupted import APP
from support.moves import three_files
from support.ollama import TAGS, VERSION, Answer, ScriptedOllama, as_json, generated, held
from support.window import FakeDialogs, environment, junk_tree, make_window, scanned, wait_idle

ANSWER = "Bytecode that Python makes again when it needs it."
CHECKS = [("GET", "/api/version"), ("GET", "/api/tags")]
GENERATE = ("POST", "/api/generate")
LABEL = "Explanation by llama3.2 via Ollama; advisory, it may be wrong:"
SETUP = "The Check on the Settings page shows how to set it up."


@pytest.fixture
def ollama() -> Iterator[ScriptedOllama]:
    """Ollama with the model, for two explanations: the checks and the answer, twice."""
    once = [VERSION, TAGS, generated(ANSWER)]
    with ScriptedOllama(*once, *once) as ollama:
        yield ollama


def _window(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    address: Address,
    *,
    dialogs: FakeDialogs | None = None,
    language: Language = "en",
) -> Window:
    env = environment(tmp_path, zone, data_dir, llm_env={URL_VARIABLE: address.url})
    return make_window(qtbot, env, dialogs=dialogs, language=language)


def _asked(ollama: ScriptedOllama) -> list[object]:
    """The facts each ``generate`` asked about."""
    return [
        json.loads(json.loads(received.body)["prompt"])
        for received in ollama.received
        if (received.method, received.path) == GENERATE
    ]


def _facts(result: Result) -> object:
    """The facts of ``result`` as a request carries them."""
    return json.loads(json.dumps(subject_of(result).facts))


def _finding(window: Window, path: Path) -> Finding:
    return next(f for f in window.findings.findings() if f.entry.path == path)


def _levels(window: Window) -> list[tuple[Path, str, bool]]:
    """Each finding's path, level and whether it is selected."""
    chosen = window.findings.selected()
    return [(f.entry.path, f.level, f in chosen) for f in window.findings.findings()]


def _listing(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def _child(item: QTreeWidgetItem, index: int) -> QTreeWidgetItem:
    child = item.child(index)
    assert child is not None
    return child


def _plan_row(tree: QTreeWidget, start: str) -> QTreeWidgetItem:
    """The plan's row that begins with ``start``."""
    root = tree.invisibleRootItem()
    groups = [_child(root, index) for index in range(root.childCount())]
    rows = [_child(group, index) for group in groups for index in range(group.childCount())]
    return next(row for row in rows if row.text(0).startswith(start))


def _plan(tree: QTreeWidget) -> list[str]:
    root = tree.invisibleRootItem()
    groups = [_child(root, index) for index in range(root.childCount())]
    return [
        line
        for group in groups
        for line in [group.text(0), *(_child(group, i).text(0) for i in range(group.childCount()))]
    ]


# --- a finding -----------------------------------------------------------------------------------


def test_a_finding_s_detail_asks_for_its_one_subject_only_on_request(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, ollama: ScriptedOllama
) -> None:
    # [0014.26] Scanning and choosing a finding ask nothing; the button asks the checks once,
    # then the one subject of that finding.
    tree = junk_tree(zone)
    window = _window(qtbot, tmp_path, zone, data_dir, ollama.address)
    page = window.findings
    assert page.explain.button.text() == "Explain (local AI)"
    assert not page.explain.button.isEnabled()  # no finding is current
    scanned(qtbot, window)
    page.tree.setCurrentItem(page.item(tree["m"]))
    assert page.explain.button.isEnabled()
    assert ollama.paths() == []
    assert page.explain.answer.text() == ""

    page.explain.button.click()
    wait_idle(qtbot, window)

    assert ollama.paths() == [*CHECKS, GENERATE]
    assert _asked(ollama) == [_facts(_finding(window, tree["m"]))]
    assert page.explain.answer.text() == f"{LABEL}\n{ANSWER}"


def test_an_answer_changes_no_level_selection_or_action_and_nothing_is_stored(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, ollama: ScriptedOllama
) -> None:
    # [0014.26] The selection the analysis made stays; no journal, no file, no data directory.
    tree = junk_tree(zone)
    window = _window(qtbot, tmp_path, zone, data_dir, ollama.address)
    page = window.findings
    scanned(qtbot, window)
    before, files = _levels(window), _listing(tmp_path)
    page.tree.setCurrentItem(page.item(tree["old"]))  # Review: not selected, and it stays so

    page.explain.button.click()
    wait_idle(qtbot, window)

    assert page.explain.answer.text() == f"{LABEL}\n{ANSWER}"
    assert _levels(window) == before
    assert page.move_button.isEnabled()
    assert _listing(tmp_path) == files
    assert not data_dir.exists()


def test_another_finding_clears_the_answer_and_a_new_analysis_too(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, ollama: ScriptedOllama
) -> None:
    # [0014.26] An answer is shown only with the result it is about.
    tree = junk_tree(zone)
    window = _window(qtbot, tmp_path, zone, data_dir, ollama.address)
    page = window.findings
    scanned(qtbot, window)
    page.tree.setCurrentItem(page.item(tree["m"]))
    page.explain.button.click()
    wait_idle(qtbot, window)

    page.tree.setCurrentItem(page.item(tree["n"]))
    assert page.explain.answer.text() == ""
    assert page.explain.button.isEnabled()

    page.tree.setCurrentItem(page.item(tree["m"]))
    page.explain.button.click()
    wait_idle(qtbot, window)
    assert page.explain.answer.text() == f"{LABEL}\n{ANSWER}"
    scanned(qtbot, window)
    assert page.explain.answer.text() == ""
    assert not page.explain.button.isEnabled()


def test_an_answer_that_comes_after_the_result_changed_is_not_shown(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.26] Choosing another finding while the answer is on its way: it is not that one's.
    tree = junk_tree(zone)
    gate = threading.Event()
    with ScriptedOllama(VERSION, TAGS, held(gate, generated(ANSWER))) as ollama:
        window = _window(qtbot, tmp_path, zone, data_dir, ollama.address)
        page = window.findings
        scanned(qtbot, window)
        page.tree.setCurrentItem(page.item(tree["m"]))
        page.explain.button.click()
        qtbot.waitUntil(lambda: GENERATE in ollama.paths(), timeout=10_000)
        page.tree.setCurrentItem(page.item(tree["n"]))
        gate.set()
        wait_idle(qtbot, window)

    assert page.explain.answer.text() == ""
    assert page.explain.button.isEnabled()


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        (
            [VERSION, as_json({"models": []})],
            "No explanation: The model is not installed: 'llama3.2' is not among the 0 models"
            f" listed. {SETUP}",
        ),
        (
            [VERSION, TAGS, as_json({"response": "", "done": True})],
            f"No explanation: The answer is empty: nothing left once cleaned. {SETUP}",
        ),
    ],
)
def test_without_an_answer_the_detail_says_why_there_is_none(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    script: list[Answer],
    expected: str,
) -> None:
    # [0014.26] 0013 item 23, in the window's words; the selection stays.
    tree = junk_tree(zone)
    with ScriptedOllama(*script) as ollama:
        window = _window(qtbot, tmp_path, zone, data_dir, ollama.address)
        page = window.findings
        scanned(qtbot, window)
        before = _levels(window)
        page.tree.setCurrentItem(page.item(tree["m"]))
        page.explain.button.click()
        wait_idle(qtbot, window)

    assert page.explain.answer.text() == expected
    assert _levels(window) == before


def test_a_refused_setting_asks_nothing_and_says_so(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.26] An address that is not loopback is refused before any connection.
    tree = junk_tree(zone)
    env = environment(tmp_path, zone, data_dir, llm_env={URL_VARIABLE: "http://192.0.2.1:11434"})
    window = make_window(qtbot, env)
    page = window.findings
    scanned(qtbot, window)
    page.tree.setCurrentItem(page.item(tree["m"]))
    page.explain.button.click()
    wait_idle(qtbot, window)

    answer = page.explain.answer.text()
    assert answer.startswith(
        "No explanation: The settings are refused: SAFECLEAN_OLLAMA_URL='http://192.0.2.1:11434': "
    )
    assert answer.endswith(SETUP)


def test_the_answer_s_label_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, ollama: ScriptedOllama
) -> None:
    # [0014.26] [0014.28] The label is the window's; the answer is shown as it is.
    tree = junk_tree(zone)
    window = _window(qtbot, tmp_path, zone, data_dir, ollama.address, language="ru")
    page = window.findings
    scanned(qtbot, window)
    page.tree.setCurrentItem(page.item(tree["m"]))
    assert page.explain.button.text() == "Объяснить (локальный ИИ)"
    page.explain.button.click()
    wait_idle(qtbot, window)

    label = "Объяснение от llama3.2 через Ollama; это лишь совет, оно может быть неверным:"
    assert page.explain.answer.text() == f"{label}\n{ANSWER}"


# --- an autostart entry --------------------------------------------------------------------------


def test_an_autostart_entry_s_detail_and_its_explanation(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, ollama: ScriptedOllama
) -> None:
    # [0014.26] The detail shows the command, what the entry replaces and its conditions; the
    # answer changes no entry and opens no journal.
    user = tmp_path / "config" / "autostart"
    system = tmp_path / "etc" / "xdg" / "autostart"
    write(system / "app.desktop", APP)
    write(user / "app.desktop", APP + b"OnlyShowIn=GNOME;\n")
    window = _window(qtbot, tmp_path, zone, data_dir, ollama.address)
    window.show_page("autostart")
    wait_idle(qtbot, window)
    page = window.autostart
    assert page.detail.text() == ""
    assert not page.explain.button.isEnabled()

    page.row("app").setSelected(True)
    item = page.selected()
    assert item is not None
    assert page.detail.text() == "\n".join(
        [
            "Command: /usr/bin/app --tray",
            f"Replaces the system entry {system / 'app.desktop'}",
            "Condition: OnlyShowIn=GNOME;",
        ]
    )
    assert ollama.paths() == []
    files = _listing(tmp_path)

    page.explain.button.click()
    wait_idle(qtbot, window)

    assert _asked(ollama) == [_facts(item)]
    assert page.explain.answer.text() == f"{LABEL}\n{ANSWER}"
    assert page.selected() == item
    assert page.disable_button.isEnabled()
    assert _listing(tmp_path) == files
    assert not data_dir.exists()


def test_another_entry_clears_the_answer(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, ollama: ScriptedOllama
) -> None:
    # [0014.26]
    user = tmp_path / "config" / "autostart"
    write(user / "app.desktop", APP)
    write(user / "other.desktop", APP.replace(b"Name=App", b"Name=Other"))
    window = _window(qtbot, tmp_path, zone, data_dir, ollama.address)
    window.show_page("autostart")
    wait_idle(qtbot, window)
    page = window.autostart
    page.row("app").setSelected(True)
    page.explain.button.click()
    wait_idle(qtbot, window)
    assert page.explain.answer.text() == f"{LABEL}\n{ANSWER}"

    page.entries.clearSelection()
    assert page.explain.answer.text() == ""
    assert page.detail.text() == ""
    assert not page.explain.button.isEnabled()
    page.row("other").setSelected(True)
    assert page.detail.text() == "Command: /usr/bin/app --tray"
    assert page.explain.button.isEnabled()


# --- a file organize leaves in place -------------------------------------------------------------


def test_a_file_that_stays_in_place_can_be_explained_and_the_plan_stays(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, ollama: ScriptedOllama
) -> None:
    # [0014.26] Only a file that stays has Explain; a move has nothing to explain.
    folder = three_files(zone)
    write(folder / "old.tmp", b"old")
    dialogs = FakeDialogs(folders=[folder])
    window = _window(qtbot, tmp_path, zone, data_dir, ollama.address, dialogs=dialogs)
    window.show_page("organize")
    wait_idle(qtbot, window)
    page = window.organize
    page.choose_button.click()
    wait_idle(qtbot, window)
    plan, files = _plan(page.plan), _listing(tmp_path)

    page.plan.setCurrentItem(_plan_row(page.plan, "a.jpg"))
    assert page.detail.text() == ""
    assert not page.explain.button.isEnabled()
    page.plan.setCurrentItem(_plan_row(page.plan, "old.tmp"))
    assert page.detail.text() == "\n".join(
        [f"Path: {folder / 'old.tmp'}", "Stays: Junk: for the cleanup: temp-files"]
    )
    assert page.explain.button.isEnabled()
    assert ollama.paths() == []

    page.explain.button.click()
    wait_idle(qtbot, window)

    assert _asked(ollama) == [{"kind": "stay", "reason": "junk", "extension": ".tmp"}]
    assert page.explain.answer.text() == f"{LABEL}\n{ANSWER}"
    assert _plan(page.plan) == plan
    assert page.move_button.isEnabled()
    assert _listing(tmp_path) == files
    assert not dialogs.asked


def test_moving_the_plan_clears_the_answer(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, ollama: ScriptedOllama
) -> None:
    # [0014.26]
    folder = three_files(zone)
    write(folder / "old.tmp", b"old")
    dialogs = FakeDialogs(folders=[folder])
    window = _window(qtbot, tmp_path, zone, data_dir, ollama.address, dialogs=dialogs)
    window.show_page("organize")
    wait_idle(qtbot, window)
    page = window.organize
    page.choose_button.click()
    wait_idle(qtbot, window)
    page.plan.setCurrentItem(_plan_row(page.plan, "old.tmp"))
    page.explain.button.click()
    wait_idle(qtbot, window)

    page.move_button.click()
    wait_idle(qtbot, window)

    assert page.explain.answer.text() == ""
    assert page.detail.text() == ""
    assert not page.explain.button.isEnabled()
