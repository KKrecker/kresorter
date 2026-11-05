"""Group by meaning (local AI) on the Organize page (decision 0018, items 24, 28, 29 and 31;
decision 0020, items 8 and 10).

Asked only once a plan is shown and the button pressed; the groups make a new plan through the
planner, shown as a plan that says where its groups come from; By kind goes back. Sort makes the
plan again with the same groups, without asking the model again, as one batch undone as any.
"""

import json
import socket
import threading
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from kresorter.llm.client import GENERATE
from kresorter.llm.group import GROUP_SCHEMA
from kresorter.llm.settings import URL_VARIABLE
from kresorter.ui.i18n import Language
from kresorter.ui.window import Window
from support.files import write
from support.moves import files
from support.ollama import TAGS, VERSION, Answer, ScriptedOllama, as_json, generated
from support.window import FakeDialogs, environment, make_window, wait_idle

CHECKS = [("GET", "/api/version"), ("GET", "/api/tags")]
NAMES = ("notes.xyz", "rome-1.jpg", "rome-2.jpg", "tax-2023.pdf", "tax-2024.pdf")
GROUPS = {
    "groups": [
        {"folder": "Trip to Rome", "files": ["rome-1.jpg", "rome-2.jpg"]},
        {"folder": "Taxes", "files": ["tax-2023.pdf", "tax-2024.pdf"]},
    ]
}
GROUPED = generated(json.dumps(GROUPS))
BY_KIND = [
    ("Images", "2 files · 20 B", "Images", "rome-1.jpg, rome-2.jpg"),
    ("Documents", "2 files · 24 B", "Documents", "tax-2023.pdf, tax-2024.pdf"),
]
BY_MEANING = [
    ("Taxes", "2 files · 24 B", "Taxes", "tax-2023.pdf, tax-2024.pdf"),
    ("Trip to Rome", "2 files · 20 B", "Trip to Rome", "rome-1.jpg, rome-2.jpg"),
]
NOTE = (
    "The local AI (llama3.2) grouped 4 of 5 files into 2 folders: the groups may be wrong. By"
    " kind goes back to the plan by kind."
)


@pytest.fixture
def folder(zone: Path) -> Path:
    """Two photos and two documents of a kind each, a file of no kind, and junk."""
    folder = zone / "Downloads"
    for name in NAMES:
        write(folder / name, name.encode())
    write(folder / "old.tmp", b"old")
    return folder


def _window(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    ollama: ScriptedOllama,
    folder: Path,
    *,
    language: Language = "en",
) -> tuple[Window, FakeDialogs]:
    """The window on Organize, the folder's plan by kind shown."""
    dialogs = FakeDialogs(folders=[folder])
    env = environment(tmp_path, zone, data_dir, llm_env={URL_VARIABLE: ollama.address.url})
    window = make_window(qtbot, env, dialogs=dialogs, language=language)
    window.show_page("organize")
    wait_idle(qtbot, window)
    window.organize.choose_button.click()
    wait_idle(qtbot, window)
    return window, dialogs


def _cards(window: Window) -> list[tuple[str, str, str, str]]:
    return [
        (card.category, card.amount.text(), card.name.text(), card.names.text())
        for card in window.organize.cards
    ]


def _stays(window: Window) -> list[tuple[str, str]]:
    tree = window.organize.stays
    rows = [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]
    return [(row.text(0), row.text(1)) for row in rows if row is not None]


def _group(qtbot: QtBot, window: Window) -> None:
    window.organize.group_button.click()
    wait_idle(qtbot, window)


def _generated(ollama: ScriptedOllama) -> list[dict[str, object]]:
    return [
        json.loads(received.body)
        for received in ollama.received
        if (received.method, received.path) == GENERATE
    ]


def test_nothing_is_sent_before_group_by_meaning_is_pressed(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, folder: Path
) -> None:
    # [0018.24] Once a plan is shown, the button is there.
    with ScriptedOllama(VERSION, TAGS, GROUPED) as ollama:
        dialogs = FakeDialogs(folders=[folder])
        env = environment(tmp_path, zone, data_dir, llm_env={URL_VARIABLE: ollama.address.url})
        window = make_window(qtbot, env, dialogs=dialogs)
        window.show_page("organize")
        wait_idle(qtbot, window)
        page = window.organize
        assert page.group_button.isHidden()
        page.choose_button.click()
        wait_idle(qtbot, window)
        connections = ollama.connections

    assert connections == 0
    assert not page.group_button.isHidden()
    assert page.group_button.isEnabled()
    assert page.group_button.text() == "Group by meaning (local AI)"
    assert page.kind_button.isHidden()
    assert page.grouped.text() == ""
    assert _cards(window) == BY_KIND


def test_a_plan_with_fewer_than_two_files_to_group_offers_no_grouping(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.24] [0018.26] A group needs two files: one alone is never sent.
    lone = zone / "Downloads"
    write(lone / "a.jpg", b"a")
    write(lone / "old.tmp", b"old")
    with ScriptedOllama(VERSION) as ollama:
        window, _ = _window(qtbot, tmp_path, zone, data_dir, ollama, lone)
        connections = ollama.connections
    assert not window.organize.group_button.isEnabled()
    assert connections == 0


def test_group_by_meaning_shows_the_groups_as_a_plan(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, folder: Path
) -> None:
    # [0018.24] [0018.25] [0018.28] [0020.2] [0020.3] The names only, sorted, numbered; the
    # answer's schema asked; a plan like any other.
    with ScriptedOllama(VERSION, TAGS, GROUPED) as ollama:
        window, _ = _window(qtbot, tmp_path, zone, data_dir, ollama, folder)
        _group(qtbot, window)
        asked, sent = ollama.paths(), _generated(ollama)

    page = window.organize
    assert asked == [*CHECKS, GENERATE]
    assert len(sent) == 1
    assert sent[0]["format"] == GROUP_SCHEMA
    prompt = sent[0]["prompt"]
    assert isinstance(prompt, str)
    numbered = {str(number): name for number, name in enumerate(NAMES, 1)}
    assert json.loads(prompt) == {"language": "English", "folders": [], "files": numbered}
    assert _cards(window) == BY_MEANING
    assert _stays(window) == [
        ("old.tmp", "Junk: for the cleanup: temp-files"),
        ("notes.xyz", "Unknown kind"),
    ]
    assert page.grouped.text() == NOTE
    assert page.group_button.isHidden()
    assert not page.kind_button.isHidden()
    assert page.kind_button.text() == "By kind"
    assert page.will.text() == "4 files will move into 2 folders."
    assert window.overview.services["organize"].note.text() == "Can be sorted into 2 folders"
    assert files(folder) == {**{name: name.encode() for name in NAMES}, "old.tmp": b"old"}


def test_by_kind_goes_back_to_the_plan_by_kind(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, folder: Path
) -> None:
    # [0018.28] Nothing is asked for it.
    with ScriptedOllama(VERSION, TAGS, GROUPED) as ollama:
        window, _ = _window(qtbot, tmp_path, zone, data_dir, ollama, folder)
        _group(qtbot, window)
        window.organize.kind_button.click()
        wait_idle(qtbot, window)
        asked = ollama.paths()

    page = window.organize
    assert asked == [*CHECKS, GENERATE]
    assert _cards(window) == BY_KIND
    assert page.grouped.text() == ""
    assert page.kind_button.isHidden()
    assert not page.group_button.isHidden()


@pytest.mark.parametrize(
    ("script", "why"),
    [
        ((VERSION, as_json({"models": []})), "Not grouped: "),
        ((VERSION, TAGS, generated("Here are your groups!")), "Not grouped: "),
    ],
)
def test_a_grouping_that_fails_says_why_and_leaves_the_plan_by_kind(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    folder: Path,
    script: tuple[Answer, ...],
    why: str,
) -> None:
    # [0018.31] [0020.8] In the words of 0013 item 23; the first batch failed.
    with ScriptedOllama(*script) as ollama:
        window, _ = _window(qtbot, tmp_path, zone, data_dir, ollama, folder)
        _group(qtbot, window)

    page = window.organize
    assert page.grouped.text().startswith(why)
    assert page.grouped.text().endswith(". The plan by kind stays.")
    assert _cards(window) == BY_KIND
    assert page.kind_button.isHidden()
    assert not page.group_button.isHidden()


def test_a_grouping_that_stopped_shows_the_groups_before_it_and_says_why(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, folder: Path
) -> None:
    # [0020.8] [0020.10] 41 files to group: the second batch's answer cannot be read.
    for n in range(36):
        write(folder / f"a{n:02d}.xyz", b"a")
    rome = {"groups": [{"folder": "Trip to Rome", "files": ["rome-1.jpg", "rome-2.jpg"]}]}
    script = (VERSION, TAGS, generated(json.dumps(rome)), generated("No."))
    with ScriptedOllama(*script) as ollama:
        window, _ = _window(qtbot, tmp_path, zone, data_dir, ollama, folder)
        _group(qtbot, window)
        asked = ollama.paths()

    page = window.organize
    assert asked == [*CHECKS, GENERATE, GENERATE]
    assert _cards(window) == [
        ("Trip to Rome", "2 files · 20 B", "Trip to Rome", "rome-1.jpg, rome-2.jpg"),
        BY_KIND[1],
    ]
    assert page.grouped.text() == (
        "The local AI (llama3.2) grouped 2 of 41 files into 1 folder, then stopped: The answer"
        ' cannot be read: the answer is not {"groups": [...]}: "No.". The groups may be wrong.'
        " By kind goes back to the plan by kind."
    )
    assert not page.kind_button.isHidden()


def test_a_grouping_that_found_no_group_leaves_the_plan_by_kind(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, folder: Path
) -> None:
    # [0018.26] [0018.31]
    alone = generated(json.dumps({"groups": [{"folder": "Rome", "files": ["rome-1.jpg"]}]}))
    with ScriptedOllama(VERSION, TAGS, alone) as ollama:
        window, _ = _window(qtbot, tmp_path, zone, data_dir, ollama, folder)
        _group(qtbot, window)

    page = window.organize
    assert page.grouped.text() == (
        "The local AI found no group of two files or more; the plan by kind stays."
    )
    assert _cards(window) == BY_KIND
    assert page.kind_button.isHidden()


def test_a_folder_gone_while_the_model_answered_is_refused_as_any(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, folder: Path
) -> None:
    # [0018.28] The groups' plan is made by the planner, which finds the folder gone.
    def renamed(client: socket.socket, stop: threading.Event) -> None:
        folder.rename(folder.with_name("Elsewhere"))
        GROUPED(client, stop)

    with ScriptedOllama(VERSION, TAGS, renamed) as ollama:
        window, _ = _window(qtbot, tmp_path, zone, data_dir, ollama, folder)
        _group(qtbot, window)

    page = window.organize
    assert page.summary.text().startswith("Refused: ")
    assert page.cards == []
    assert page.grouped.text() == ""
    assert page.kind_button.isHidden()
    assert files(folder.with_name("Elsewhere")) == {
        **{name: name.encode() for name in NAMES},
        "old.tmp": b"old",
    }


def test_sort_keeps_the_groups_without_asking_again_and_its_batch_is_undone_as_any(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, folder: Path
) -> None:
    # [0018.29] The plan made again under the lock with the same groups.
    with ScriptedOllama(VERSION, TAGS, GROUPED) as ollama:
        window, dialogs = _window(qtbot, tmp_path, zone, data_dir, ollama, folder)
        _group(qtbot, window)
        page = window.organize
        page.move_button.click()
        wait_idle(qtbot, window)
        asked = ollama.paths()

    assert asked == [*CHECKS, GENERATE]
    [confirmation] = dialogs.asked
    assert confirmation.details == (
        "tax-2023.pdf → Taxes/",
        "tax-2024.pdf → Taxes/",
        "rome-1.jpg → Trip to Rome/",
        "rome-2.jpg → Trip to Rome/",
    )
    assert files(folder) == {
        "Taxes/tax-2023.pdf": b"tax-2023.pdf",
        "Taxes/tax-2024.pdf": b"tax-2024.pdf",
        "Trip to Rome/rome-1.jpg": b"rome-1.jpg",
        "Trip to Rome/rome-2.jpg": b"rome-2.jpg",
        "notes.xyz": b"notes.xyz",
        "old.tmp": b"old",
    }
    assert page.grouped.text() == ""
    assert page.group_button.isHidden()
    page.batches.setCurrentItem(page.batch_row(1))
    page.undo_button.click()
    wait_idle(qtbot, window)
    assert files(folder) == {**{name: name.encode() for name in NAMES}, "old.tmp": b"old"}


def test_group_by_meaning_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, folder: Path
) -> None:
    # [0018.25] [0018.28] [0020.10] The folder names asked in the window's language.
    with ScriptedOllama(VERSION, TAGS, GROUPED) as ollama:
        window, _ = _window(qtbot, tmp_path, zone, data_dir, ollama, folder, language="ru")
        page = window.organize
        assert page.group_button.text() == "Сгруппировать по смыслу (локальный ИИ)"
        _group(qtbot, window)
        sent = _generated(ollama)

    prompt = sent[0]["prompt"]
    assert isinstance(prompt, str)
    assert json.loads(prompt)["language"] == "Russian"
    assert page.kind_button.text() == "По типу"
    assert page.grouped.text() == (
        "Локальный ИИ (llama3.2) сгруппировал 4 из 5 файлов в 2 папки: группы могут быть"
        " неверными. «По типу» возвращает план по типам."
    )
