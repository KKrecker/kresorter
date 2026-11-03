"""The Settings page: the language, which applies the next time the window opens; on Windows
the machine scope of autostart, turned on only after a confirmation that says what is read; a
Check of the local AI that runs the checks of ``kresorter llm status`` and shows each; the data
directory's path; a card each, the page scrolling under its head. The page says when the
settings file was not used, and the file is written only when the user changes a setting
(decision 0014, items 27, 36, 37 and 55)."""

import io
import json
import socket
from collections.abc import Mapping
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFrame, QLabel, QWidget
from pytestqt.qtbot import QtBot

from fakes import FakeRegistry
from kresorter.analysis.score import Level
from kresorter.autostart.registry import Hive, RegValue, ValueKind
from kresorter.autostart.run_keys import RUN
from kresorter.cli_llm import run_status
from kresorter.core.heuristics import Platform
from kresorter.llm.settings import MODEL_VARIABLE, URL_VARIABLE, Address
from kresorter.ui.i18n import Language
from kresorter.ui.settings import Settings, load
from kresorter.ui.settings_page import SettingsPage
from kresorter.ui.theme import LIGHT
from kresorter.ui.window import Window
from support.cli import autostart_context, run, scan_context
from support.ollama import TAGS, VERSION, Answer, ScriptedOllama, as_json
from support.window import FakeDialogs, children, environment, make_window, settled, wait_idle

MACHINE = (
    "Machine-wide entries (HKLM, services, scheduled tasks, the common startup folder) were not"
    " read; turn them on in Settings."
)
READ = (
    "The Autostart page will also read the machine-wide entries: the HKLM Run keys, the"
    " services, the scheduled tasks and the common startup folder. They are only read;"
    " nothing in them is changed."
)
NOT_USED = "The settings file was not used: {}. The defaults apply until a setting is changed."
AVAILABLE = (
    "Explanations are available: Explain (local AI) on a finding, an autostart entry or a file"
    " that stays in place."
)
SETUP = [
    "Explanations are unavailable; kresorter works as usual without them.",
    "To set them up (kresorter installs nothing itself):",
]
INSTALL = "Install Ollama from https://ollama.com/download and start it."
AGAIN = "Check again."
SETTINGS = (
    "Settings, from the environment the window started in: KRESORTER_OLLAMA_URL (a loopback"
    " address, default http://127.0.0.1:11434) and KRESORTER_OLLAMA_MODEL (default llama3.2)."
)
AGENT = RegValue("Agent", ValueKind.REG_SZ, r"C:\agent.exe")
SYNC = RegValue("Sync", ValueKind.REG_SZ, r"C:\sync.exe")


@pytest.fixture
def registry() -> FakeRegistry:
    """A user entry, and a machine-wide one."""
    return FakeRegistry({(Hive.HKCU, RUN): [SYNC], (Hive.HKLM, RUN): [AGENT]})


def _window(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    *,
    platform: Platform = "linux",
    registry: FakeRegistry | None = None,
    dialogs: FakeDialogs | None = None,
    llm_env: Mapping[str, str] | None = None,
    language: Language = "en",
) -> Window:
    """The window on its Settings page."""
    env = environment(
        tmp_path, zone, data_dir, platform=platform, registry=registry, llm_env=llm_env
    )
    window = make_window(qtbot, env, dialogs=dialogs, language=language)
    window.show_page("settings")
    wait_idle(qtbot, window)
    return window


def _choices(window: Window) -> list[str]:
    combo = window.settings.language
    return [combo.itemText(index) for index in range(combo.count())]


def _saved(data_dir: Path) -> object:
    return json.loads((data_dir / "settings.json").read_bytes())


def _lines(page: SettingsPage) -> list[str]:
    """What the check found: Ollama, the model, then the rest."""
    return [*(found.text() for found in page.found), *page.check.text().splitlines()]


def _dots(page: SettingsPage) -> list[object]:
    return [found.dot.property("dot") for found in page.found]


def _titles(card: QFrame) -> list[str]:
    return [
        label.text()
        for label in card.findChildren(QLabel)
        if label.property("role") == "card-title"
    ]


def _right(widget: QWidget, card: QFrame) -> int:
    """The right edge of ``widget`` in ``card``."""
    return widget.mapTo(card, widget.rect().topRight()).x()


def _listed(qtbot: QtBot, window: Window) -> list[str]:
    """The names the Autostart page lists, once it has read them again."""
    window.show_page("autostart")
    wait_idle(qtbot, window)
    root = window.autostart.entries.invisibleRootItem()
    groups = children(root)
    return [row.text(0) for group in groups for row in children(group)]


# --- the page ------------------------------------------------------------------------------------


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_the_page_shows_the_language_and_the_data_folder_and_writes_nothing(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, platform: Platform
) -> None:
    # [0014.27] No machine scope outside Windows; opening the page writes nothing [0014.35].
    window = _window(qtbot, tmp_path, zone, data_dir, platform=platform)
    page = window.settings

    assert window.pages.currentWidget() is page
    assert _choices(window) == ["As the system", "English", "Русский"]
    assert page.language.currentIndex() == 0
    assert page.language.accessibleName() == "Language"
    assert page.language_note.text() == "A new language applies the next time the window opens."
    assert page.data_dir.toolTip() == str(data_dir)
    assert page.machine.isHidden()
    assert page.unused.isHidden()
    assert _lines(page) == ["", ""]
    assert page.result.text() == ""
    assert page.current == Settings()
    assert not data_dir.exists()


def test_a_language_chosen_is_saved_and_applies_the_next_time_the_window_opens(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.27] [0014.35] The window keeps its language; the next one is opened in Russian.
    window = _window(qtbot, tmp_path, zone, data_dir)
    page = window.settings

    page.language.setCurrentIndex(2)

    assert _saved(data_dir) == {"language": "ru", "include_machine": False}
    assert page.result.text() == "Saved."
    assert page.current == Settings(language="ru")
    assert window.sidebar.item(0).text() == "Overview"
    assert load(scan_context(tmp_path, zone, data_dir)).settings == Settings(language="ru")


def test_choosing_the_language_already_set_writes_nothing(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.27] [0014.35]
    path = settled(data_dir, language="en")
    window = _window(qtbot, tmp_path, zone, data_dir)
    page = window.settings
    assert page.language.currentIndex() == 1
    before = path.stat().st_mtime_ns

    page.language.setCurrentIndex(1)

    assert path.stat().st_mtime_ns == before
    assert page.result.text() == ""


def test_a_setting_that_cannot_be_saved_says_why_and_stays_as_it_was(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.27] [0014.35] The data directory cannot be made: nothing changes.
    data_dir.parent.mkdir(parents=True)
    data_dir.write_bytes(b"not a directory")
    window = _window(qtbot, tmp_path, zone, data_dir)
    page = window.settings

    page.language.setCurrentIndex(2)

    assert page.result.text().startswith("Not saved: The data folder cannot be used: ")
    assert page.language.currentIndex() == 0
    assert page.current == Settings()
    assert data_dir.read_bytes() == b"not a directory"


# --- a broken file -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "why"),
    [
        (b'{"language": "fr"}', 'A setting has a wrong or unknown value: language="fr"'),
        (b"[]", "The file is not a JSON object"),
    ],
)
def test_a_broken_file_is_not_used_and_the_page_says_so(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, content: bytes, why: str
) -> None:
    # [0014.36] The defaults, the page says why, and the file stays until a setting changes.
    path = settled(data_dir)
    path.write_bytes(content)
    window = _window(qtbot, tmp_path, zone, data_dir)
    page = window.settings

    assert page.unused.text() == NOT_USED.format(why)
    assert not page.unused.isHidden()
    assert page.language.currentIndex() == 0
    assert path.read_bytes() == content

    page.language.setCurrentIndex(1)

    assert _saved(data_dir) == {"language": "en", "include_machine": False}
    assert page.unused.isHidden()


def test_a_file_that_is_not_json_is_named_with_the_parser_s_words(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.36]
    settled(data_dir).write_bytes(b"{not json")
    window = _window(qtbot, tmp_path, zone, data_dir)

    text = window.settings.unused.text()
    assert text.startswith("The settings file was not used: The file is not valid JSON: Expecting")
    assert text.endswith(". The defaults apply until a setting is changed.")


# --- the machine scope ---------------------------------------------------------------------------


def test_on_windows_the_machine_scope_is_off_until_turned_on_after_confirmation(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, registry: FakeRegistry
) -> None:
    # [0014.37] Off by default: the Autostart page says what it did not read, and reads none
    # of it; turning it on asks first, and a cancel leaves it off.
    dialogs = FakeDialogs(confirm=False)
    window = _window(
        qtbot, tmp_path, zone, data_dir, platform="windows", registry=registry, dialogs=dialogs
    )
    page = window.settings
    assert not page.machine.isHidden()
    assert page.machine.text() == "Read machine-wide autostart entries"
    assert not page.machine.isChecked()
    assert _listed(qtbot, window) == ["Sync"]
    assert window.autostart.machine.text() == MACHINE
    assert not window.autostart.machine.isHidden()
    assert Hive.HKLM not in {hive for hive, _ in registry.reads}

    window.show_page("settings")
    page.machine.click()

    [asked] = dialogs.asked
    assert (asked.title, asked.text, asked.action) == ("Read machine-wide entries", READ, "Read")
    assert not asked.danger
    assert not page.machine.isChecked()
    assert not data_dir.exists()

    dialogs.answer = True
    page.machine.click()

    assert page.machine.isChecked()
    assert _saved(data_dir) == {"language": "system", "include_machine": True}
    assert page.result.text() == "Saved."
    assert _listed(qtbot, window) == ["Sync", "Agent"]
    assert window.autostart.machine.isHidden()


def test_turning_the_machine_scope_off_asks_nothing_and_keeps_the_language(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, registry: FakeRegistry
) -> None:
    # [0014.37]
    settled(data_dir, language="ru", include_machine=True)
    dialogs = FakeDialogs()
    window = _window(
        qtbot, tmp_path, zone, data_dir, platform="windows", registry=registry, dialogs=dialogs
    )
    page = window.settings
    assert page.machine.isChecked()
    assert _listed(qtbot, window) == ["Sync", "Agent"]

    window.show_page("settings")
    page.machine.click()

    assert dialogs.asked == []
    assert not page.machine.isChecked()
    assert _saved(data_dir) == {"language": "ru", "include_machine": False}
    assert _listed(qtbot, window) == ["Sync"]


def test_a_machine_scope_that_cannot_be_saved_stays_off(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, registry: FakeRegistry
) -> None:
    # [0014.37] [0014.35]
    data_dir.parent.mkdir(parents=True)
    data_dir.write_bytes(b"not a directory")
    window = _window(qtbot, tmp_path, zone, data_dir, platform="windows", registry=registry)
    page = window.settings

    page.machine.click()

    assert not page.machine.isChecked()
    assert page.result.text().startswith("Not saved: ")
    assert _listed(qtbot, window) == ["Sync"]


def test_the_cli_reads_the_machine_scope_only_with_include_machine(
    tmp_path: Path, zone: Path, data_dir: Path, registry: FakeRegistry
) -> None:
    # [0014.37] What the window remembers is not the CLI's.
    settled(data_dir, include_machine=True)
    scan = scan_context(tmp_path, zone, data_dir, platform="windows")
    auto = autostart_context("windows", tmp_path, registry)

    _, out, _ = run(["autostart", "list", "--json"], scan, auto)

    data = json.loads(out)
    assert data["include_machine"] is False
    assert [item["name"] for item in data["items"]] == ["Sync"]
    assert Hive.HKLM not in {hive for hive, _ in registry.reads}


# --- the check of the local AI -------------------------------------------------------------------


def _closed() -> Address:
    """A loopback port nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return Address("127.0.0.1", port)


def _status(env: Mapping[str, str]) -> list[str]:
    out = io.StringIO()
    run_status(env, out)
    return out.getvalue().splitlines()


def _checked(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, env: Mapping[str, str]
) -> list[str]:
    window = _window(qtbot, tmp_path, zone, data_dir, llm_env=env)
    window.settings.check_button.click()
    wait_idle(qtbot, window)
    assert _dots(window.settings) == ["review", "review"]  # [0014.55]
    return _lines(window.settings)


def _steps(*steps: str) -> list[str]:
    return [f"{n}. {step}" for n, step in enumerate([*steps, AGAIN], start=1)]


@pytest.mark.parametrize(
    ("script", "rest"),
    [
        ([VERSION, TAGS], [AVAILABLE]),
        (
            [VERSION, as_json({"models": []})],
            [*SETUP, *_steps("Download the model: ollama pull llama3.2"), SETTINGS],
        ),
        (
            [as_json({"name": "not ollama"})],
            [*SETUP, *_steps(INSTALL, "Download the model: ollama pull llama3.2"), SETTINGS],
        ),
    ],
)
def test_the_check_runs_the_checks_of_llm_status_and_shows_each(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, script: list[Answer], rest: list[str]
) -> None:
    # [0014.27] The Ollama and Model lines are those of 'kresorter llm status'; nothing is
    # asked before the button, and the check asks no explanation.
    with ScriptedOllama(*script, *script) as ollama:
        env = {URL_VARIABLE: ollama.address.url}
        window = _window(qtbot, tmp_path, zone, data_dir, llm_env=env)
        assert ollama.paths() == []
        window.settings.check_button.click()
        wait_idle(qtbot, window)
        shown = _lines(window.settings)
        asked = ollama.paths()
        cli = _status(env)

    assert shown[:2] == cli[:2]
    assert shown[2:] == rest
    assert ("POST", "/api/generate") not in asked


@pytest.mark.parametrize(
    ("variables", "rest"),
    [
        (
            {URL_VARIABLE: "http://192.0.2.1:11434"},
            [*SETUP, *_steps("Download the model: ollama pull llama3.2"), SETTINGS],
        ),
        ({MODEL_VARIABLE: "no model!"}, [*SETUP, *_steps(), SETTINGS]),
    ],
)
def test_a_refused_setting_is_checked_no_further(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    variables: dict[str, str],
    rest: list[str],
) -> None:
    # [0014.27] As 'kresorter llm status': the refused setting, and no connection.
    env = {URL_VARIABLE: _closed().url, **variables}
    shown = _checked(qtbot, tmp_path, zone, data_dir, env)

    assert shown[:2] == _status(env)[:2]
    assert "refused setting" in "\n".join(shown[:2])
    assert shown[2:] == rest


def test_ollama_that_is_not_running_is_named_with_its_address(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.27]
    address = _closed()
    env = {URL_VARIABLE: address.url}
    shown = _checked(qtbot, tmp_path, zone, data_dir, env)

    assert shown[:2] == _status(env)[:2]
    assert shown[0].startswith(f"Ollama: not reachable at {address.url} (")
    assert shown[2:] == [
        *SETUP,
        *_steps(INSTALL, "Download the model: ollama pull llama3.2"),
        SETTINGS,
    ]


# --- in Russian ----------------------------------------------------------------------------------


def test_the_page_in_russian(qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path) -> None:
    # [0014.27] [0014.28]
    with ScriptedOllama(VERSION, TAGS) as ollama:
        env = {URL_VARIABLE: ollama.address.url}
        window = _window(qtbot, tmp_path, zone, data_dir, llm_env=env, language="ru")
        page = window.settings
        page.check_button.click()
        wait_idle(qtbot, window)

    assert _choices(window)[1:] == ["English", "Русский"]
    assert page.language_note.text() == "Новый язык применится при следующем открытии окна."
    assert _titles(page.data_card) == ["Папка данных"]
    assert page.address.text() == f"Адрес: {ollama.address.url} · Модель: llama3.2"
    assert _lines(page)[:2] == [
        f"Ollama: работает по адресу {ollama.address.url} (версия 0.6.2)",
        "Модель: llama3.2: установлена",
    ]
    page.language.setCurrentIndex(1)
    assert page.result.text() == "Сохранено."


# --- the cards [0014.55] -------------------------------------------------------------------------


@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_a_card_each_the_page_scrolling_under_its_head(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, platform: Platform
) -> None:
    # [0014.55] [0014.46] The machine-wide entries on Windows only; the language's choice and
    # Check at the right of their titles.
    window = _window(qtbot, tmp_path, zone, data_dir, platform=platform)
    page = window.settings
    cards = [page.language_card, page.machine_card, page.ai_card, page.data_card]
    assert [part.property("role") for part in cards] == ["card"] * 4
    assert [_titles(part) for part in cards] == [
        ["Language"],
        ["Autostart"],
        ["Local AI (Ollama)"],
        ["Data folder"],
    ]
    assert page.machine_card.isHidden() == (platform != "windows")
    inside = page.controls.layout()
    assert inside is not None
    order = [page.unused, *cards, page.result]
    places = [inside.indexOf(part) for part in order]
    assert places == sorted(places)
    assert places[0] >= 0
    assert (page.area.widget(), page.area.widgetResizable()) == (page.controls, True)
    assert page.head.parentWidget() is page
    language, ai = page.language_card, page.ai_card
    assert _right(page.language, language) == _right(page.language_note, language)
    assert _right(page.check_button, ai) == _right(page.address, ai)


@pytest.mark.parametrize(
    ("env", "shown"),
    [
        ({}, "Address: http://127.0.0.1:11434 · Model: llama3.2"),
        (
            {URL_VARIABLE: "http://127.0.0.1:9", MODEL_VARIABLE: "no model!"},
            "Address: http://127.0.0.1:9 · Model: no model!",
        ),
    ],
)
def test_the_local_ai_s_address_and_model_as_the_environment_gives_them(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, env: dict[str, str], shown: str
) -> None:
    # [0014.55] In secondary text; whether they are refused is for Check to say.
    window = _window(qtbot, tmp_path, zone, data_dir, llm_env=env)
    assert window.settings.address.text() == shown
    assert window.settings.address.property("role") == "secondary"


@pytest.mark.parametrize(
    ("script", "dots"),
    [
        ([VERSION, TAGS], ["safe", "safe"]),
        ([VERSION, as_json({"models": []})], ["safe", "review"]),
        ([as_json({"name": "not ollama"})], ["review", "review"]),
    ],
)
def test_each_check_has_a_dot_in_the_safe_colour_when_it_passed_or_the_review_one(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, script: list[Answer], dots: list[str]
) -> None:
    # [0014.55] Ollama, then the model; none before a check.
    with ScriptedOllama(*script) as ollama:
        window = _window(
            qtbot, tmp_path, zone, data_dir, llm_env={URL_VARIABLE: ollama.address.url}
        )
        page = window.settings
        assert [found.isHidden() for found in page.found] == [True, True]
        page.check_button.click()
        wait_idle(qtbot, window)
    assert [found.isHidden() for found in page.found] == [False, False]
    assert _dots(page) == dots
    drawn = [found.dot.grab().toImage() for found in page.found]
    colours = [image.pixelColor(4, 4).name().upper() for image in drawn]
    assert colours == [LIGHT.levels[Level(kind)] for kind in dots]


def test_the_data_folder_from_the_home_folder(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, home: Path
) -> None:
    # [0014.55] The whole path in its tooltip, in secondary text.
    window = _window(qtbot, tmp_path, zone, data_dir)
    page = window.settings
    assert (page.data_dir.text(), page.data_dir.toolTip()) == ("~/data/kresorter", str(data_dir))
    assert page.data_dir.property("role") == "secondary"


@pytest.mark.parametrize("language", ["en", "ru"])
def test_the_version_under_the_data_folder(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, language: Language
) -> None:
    # [0015.4] in both languages, the card's last line
    window = _window(qtbot, tmp_path, zone, data_dir, language=language)
    page = window.settings
    shown = [label for label in page.data_card.findChildren(QLabel) if label.isVisibleTo(page)]
    assert [label.text() for label in shown][-2:] == [page.data_dir.text(), "Kresorter 0.1.0"]
    assert shown[-1].property("role") == "secondary"
