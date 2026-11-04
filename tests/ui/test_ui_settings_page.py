"""The Settings page: the language, which applies the next time the window opens; on Windows
the machine scope of autostart, turned on only after a confirmation that says what is read; a
Check of the local AI that runs the checks of ``kresorter llm status`` and shows each; the data
directory's path; a card each, the page scrolling under its head. The page says when the
settings file was not used, and the file is written only when the user changes a setting
(decision 0014, items 27, 36, 37 and 55). The theme, saved and applied at once (decision 0018,
items 1 and 2)."""

import io
import json
import socket
from collections.abc import Mapping
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget
from pytestqt.qtbot import QtBot

from fakes import FakeRegistry
from kresorter.analysis.score import Level
from kresorter.autostart.registry import Hive, RegValue, ValueKind
from kresorter.autostart.run_keys import RUN
from kresorter.cli_llm import run_status
from kresorter.core.heuristics import Platform
from kresorter.llm.machine import GIB, Machine
from kresorter.llm.settings import MODEL_VARIABLE, URL_VARIABLE, Address
from kresorter.ui.i18n import Language
from kresorter.ui.settings import Settings, load
from kresorter.ui.settings_page import SettingsPage
from kresorter.ui.theme import DARK, LIGHT, style_sheet
from kresorter.ui.window import Window
from support.cli import autostart_context, run, scan_context
from support.host import native
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


def _themes(window: Window) -> list[str]:
    combo = window.settings.theme
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

    assert _saved(data_dir) == {
        "language": "ru",
        "include_machine": False,
        "skipped_zones": [],
        "theme": "system",
    }
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


# --- the model [0018.32] [0018.33] [0018.34] ------------------------------------------------------

LISTED = as_json(
    {"models": [{"name": "llama3.2:latest"}, {"name": "qwen2.5:3b"}, {"name": "no model!"}]}
)
CHECKS = [("GET", "/api/version"), ("GET", "/api/tags")]


def _models(page: SettingsPage) -> list[str]:
    return [page.model.itemText(index) for index in range(page.model.count())]


def _checked(qtbot: QtBot, window: Window) -> SettingsPage:
    page = window.settings
    page.check_button.click()
    wait_idle(qtbot, window)
    return page


def test_check_lists_the_models_ollama_has_in_a_choice(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.32] Only names a model may have; the one in use is the one chosen.
    with ScriptedOllama(VERSION, LISTED) as ollama:
        env = {URL_VARIABLE: ollama.address.url}
        window = _window(qtbot, tmp_path, zone, data_dir, llm_env=env)
        assert window.settings.model.isHidden()
        page = _checked(qtbot, window)

    assert not page.model.isHidden()
    assert _models(page) == ["llama3.2:latest", "qwen2.5:3b"]
    assert page.model.currentIndex() == 0
    assert page.model.isEnabled()
    assert page.model.accessibleName() == "Model"
    assert page.model_note.isHidden()
    assert not data_dir.exists()


def test_a_model_chosen_is_saved_and_used_by_the_check_and_named_in_the_sidebar(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.32] [0018.34] Chosen, the check runs again with it.
    with ScriptedOllama(VERSION, LISTED, VERSION, LISTED) as ollama:
        url = ollama.address.url
        window = _window(qtbot, tmp_path, zone, data_dir, llm_env={URL_VARIABLE: url})
        page = _checked(qtbot, window)
        page.model.setCurrentIndex(1)
        wait_idle(qtbot, window)
        asked = ollama.paths()

    assert _saved(data_dir) == {
        "language": "system",
        "include_machine": False,
        "skipped_zones": [],
        "theme": "system",
        "model": "qwen2.5:3b",
    }
    assert page.current == Settings(model="qwen2.5:3b")
    assert page.result.text() == "Saved."
    assert asked == [*CHECKS, *CHECKS]
    assert page.address.text() == f"Address: {url} · Model: qwen2.5:3b"
    assert _lines(page)[1] == "Model: qwen2.5:3b: installed"
    assert window.sidebar.ai.text() == "AI explanations: qwen2.5:3b"
    assert page.model.currentIndex() == 1


def test_the_window_opens_with_the_model_remembered(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.32] [0018.34]
    settled(data_dir, model="qwen2.5:3b")
    window = _window(qtbot, tmp_path, zone, data_dir)
    assert window.settings.address.text() == "Address: http://127.0.0.1:11434 · Model: qwen2.5:3b"
    assert window.sidebar.ai.text() == "AI explanations: qwen2.5:3b"


def test_the_environment_s_model_wins_and_the_card_says_so(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.32] Before a check too; the choice cannot change it.
    settled(data_dir, model="qwen2.5:3b")
    with ScriptedOllama(VERSION, LISTED) as ollama:
        url = ollama.address.url
        env = {URL_VARIABLE: url, MODEL_VARIABLE: "llama3.2"}
        window = _window(qtbot, tmp_path, zone, data_dir, llm_env=env)
        note = window.settings.model_note
        assert note.text() == (
            "KRESORTER_OLLAMA_MODEL sets the model: llama3.2. The model chosen here applies"
            " once it is unset."
        )
        assert not note.isHidden()
        page = _checked(qtbot, window)

    assert page.address.text() == f"Address: {url} · Model: llama3.2"
    assert _lines(page)[1] == "Model: llama3.2: installed"
    assert window.sidebar.ai.text() == "AI explanations: llama3.2"
    assert page.model.currentIndex() == 0
    assert not page.model.isEnabled()


def test_a_model_that_cannot_be_saved_is_not_used(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.32] [0014.35] Nothing changes, and nothing is asked again.
    data_dir.parent.mkdir(parents=True)
    data_dir.write_bytes(b"not a directory")
    with ScriptedOllama(VERSION, LISTED, VERSION, LISTED) as ollama:
        env = {URL_VARIABLE: ollama.address.url}
        window = _window(qtbot, tmp_path, zone, data_dir, llm_env=env)
        page = _checked(qtbot, window)
        page.model.setCurrentIndex(1)
        wait_idle(qtbot, window)
        asked = ollama.paths()

    assert page.result.text().startswith("Not saved: The data folder cannot be used: ")
    assert page.model.currentIndex() == 0
    assert page.current == Settings()
    assert asked == CHECKS
    assert window.sidebar.ai.text() == "AI explanations: llama3.2"


def test_the_card_recommends_a_model_for_the_machine_and_how_to_get_it(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.33] kresorter installs nothing.
    env = environment(tmp_path, zone, data_dir, machine=Machine(16 * GIB, 8))
    window = make_window(qtbot, env)
    size = window.translator.size(16 * GIB)
    assert window.settings.recommended.text() == (
        f"Recommended for this computer ({size} of memory, 8 processors): qwen2.5:7b; Qwen 2.5"
        " writes Russian as well as English. To get it: ollama pull qwen2.5:7b (kresorter"
        " installs nothing itself)."
    )
    assert window.settings.ai_card.isAncestorOf(window.settings.recommended)


@pytest.mark.parametrize(
    ("machine", "language", "shown"),
    [
        (
            Machine(8 * GIB, 1),
            "en",
            "Recommended for this computer (8.0 GiB of memory, 1 processor): qwen2.5:1.5b;",
        ),
        (
            Machine(None, None),
            "ru",
            "Рекомендуется для этого компьютера (память неизвестна, число процессоров"
            " неизвестно): qwen2.5:1.5b;",
        ),
        (
            Machine(32 * GIB, 2),
            "ru",
            "Рекомендуется для этого компьютера (32,0 ГиБ памяти, 2 процессора): qwen2.5:7b;",
        ),
    ],
)
def test_the_recommendation_says_what_it_comes_from(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    machine: Machine,
    language: Language,
    shown: str,
) -> None:
    # [0018.33]
    env = environment(tmp_path, zone, data_dir, machine=machine)
    window = make_window(qtbot, env, language=language)
    assert window.settings.recommended.text().startswith(shown)


def test_the_recommendation_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.33]
    env = environment(tmp_path, zone, data_dir, machine=Machine(4 * GIB, 8))
    window = make_window(qtbot, env, language="ru")
    assert window.settings.recommended.text().endswith(
        ": qwen2.5:1.5b; Qwen 2.5 пишет и по-русски, и по-английски. Чтобы получить её: ollama"
        " pull qwen2.5:1.5b (kresorter сам ничего не устанавливает)."
    )


# --- a restart [0018.3] [0018.4] -----------------------------------------------------------------

RESTART = (
    "Restart the window?",
    "The window opens again in the new language, on this page. A task that changes files"
    " ends first.",
    (),
    "Restart now",
    False,
)


def _asked(dialogs: FakeDialogs) -> list[tuple[object, ...]]:
    return [(a.title, a.text, a.details, a.action, a.danger) for a in dialogs.asked]


def test_a_new_language_offers_a_restart_and_declined_it_applies_the_next_time(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.3] As the note says.
    dialogs = FakeDialogs(confirm=False)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs=dialogs)
    page = window.settings

    page.language.setCurrentIndex(2)

    assert _asked(dialogs) == [RESTART]
    assert window.isVisible()
    assert window.restart_page is None
    assert page.result.text() == "Saved."
    assert page.current == Settings(language="ru")
    assert window.sidebar.item(0).text() == "Overview"
    assert page.language_note.text() == "A new language applies the next time the window opens."


def test_restart_now_closes_the_window_to_open_it_again_on_the_same_page(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.3] [0018.4]
    dialogs = FakeDialogs(confirm=True)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs=dialogs)

    window.settings.language.setCurrentIndex(1)

    assert _asked(dialogs) == [RESTART]
    assert not window.isVisible()
    assert window.restart_page == "settings"
    assert _saved(data_dir) == {
        "language": "en",
        "include_machine": False,
        "skipped_zones": [],
        "theme": "system",
    }


def test_a_restart_is_offered_in_the_window_s_language(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.3]
    dialogs = FakeDialogs(confirm=False)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs=dialogs, language="ru")

    window.settings.language.setCurrentIndex(1)

    assert _asked(dialogs) == [
        (
            "Перезапустить окно?",
            "Окно откроется снова на новом языке, на этой же странице. Задача, которая меняет"
            " файлы, сначала завершится.",
            (),
            "Перезапустить сейчас",
            False,
        )
    ]


def test_no_restart_is_offered_for_the_language_already_set_or_the_theme(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.3]
    settled(data_dir, language="en")
    dialogs = FakeDialogs(confirm=True)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs=dialogs)
    page = window.settings
    page.language.setCurrentIndex(1)
    page.theme.setCurrentIndex(2)

    assert page.result.text() == "Saved."
    assert dialogs.asked == []
    assert window.isVisible()
    assert window.restart_page is None


def test_no_restart_is_offered_for_a_language_that_cannot_be_saved(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.3]
    data_dir.parent.mkdir(parents=True)
    data_dir.write_bytes(b"not a directory")
    dialogs = FakeDialogs(confirm=True)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs=dialogs)

    window.settings.language.setCurrentIndex(2)

    assert window.settings.result.text().startswith("Not saved: ")
    assert dialogs.asked == []
    assert window.isVisible()
    assert window.restart_page is None


# --- the theme [0018.1] [0018.2] -----------------------------------------------------------------


def test_the_appearance_card_has_a_choice_of_system_light_and_dark(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.1] The system's theme until another is chosen.
    window = _window(qtbot, tmp_path, zone, data_dir)
    page = window.settings
    assert _titles(page.appearance_card) == ["Appearance"]
    assert _themes(window) == ["System", "Light", "Dark"]
    assert page.theme.accessibleName() == "Appearance"
    assert page.theme.currentIndex() == 0
    assert (window.look.theme, window.look.palette) == ("system", LIGHT)
    assert not data_dir.exists()


def test_a_theme_chosen_is_saved_and_applied_at_once(
    qtbot: QtBot, qapp: QApplication, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.2] Dark whatever the system says, then light.
    window = _window(qtbot, tmp_path, zone, data_dir)
    page = window.settings

    page.theme.setCurrentIndex(2)

    assert _saved(data_dir) == {
        "language": "system",
        "include_machine": False,
        "skipped_zones": [],
        "theme": "dark",
    }
    assert page.result.text() == "Saved."
    assert page.current == Settings(theme="dark")
    assert window.look.palette is DARK
    assert window.styleSheet() == style_sheet(DARK)
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert window.look.palette is DARK

    page.theme.setCurrentIndex(1)

    assert _saved(data_dir) == {
        "language": "system",
        "include_machine": False,
        "skipped_zones": [],
        "theme": "light",
    }
    assert window.look.palette is LIGHT
    assert window.styleSheet() == style_sheet(LIGHT)


@pytest.mark.parametrize(("theme", "index"), [("light", 1), ("dark", 2)])
def test_the_window_opens_in_the_theme_remembered(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, theme: str, index: int
) -> None:
    # [0018.2]
    settled(data_dir, theme=theme)
    window = _window(qtbot, tmp_path, zone, data_dir)
    assert window.settings.theme.currentIndex() == index
    assert window.look.theme == theme
    palette = DARK if theme == "dark" else LIGHT
    assert window.look.palette is palette
    assert window.styleSheet() == style_sheet(palette)


def test_a_theme_that_cannot_be_saved_is_not_applied(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.2] [0014.35] The data directory cannot be made: the theme stays as it was.
    data_dir.parent.mkdir(parents=True)
    data_dir.write_bytes(b"not a directory")
    window = _window(qtbot, tmp_path, zone, data_dir)
    page = window.settings

    page.theme.setCurrentIndex(2)

    assert page.result.text().startswith("Not saved: The data folder cannot be used: ")
    assert page.theme.currentIndex() == 0
    assert (window.look.theme, window.look.palette) == ("system", LIGHT)
    assert page.current == Settings()


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

    assert _saved(data_dir) == {
        "language": "en",
        "include_machine": False,
        "skipped_zones": [],
        "theme": "system",
    }
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
    assert _saved(data_dir) == {
        "language": "system",
        "include_machine": True,
        "skipped_zones": [],
        "theme": "system",
    }
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
    assert _saved(data_dir) == {
        "language": "ru",
        "include_machine": False,
        "skipped_zones": [],
        "theme": "system",
    }
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
    assert _titles(page.appearance_card) == ["Оформление"]
    assert _themes(window) == ["Как в системе", "Светлая", "Тёмная"]
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
    cards = [
        page.language_card,
        page.appearance_card,
        page.machine_card,
        page.ai_card,
        page.data_card,
    ]
    assert [part.property("role") for part in cards] == ["card"] * 5
    assert [_titles(part) for part in cards] == [
        ["Language"],
        ["Appearance"],
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
    assert _right(page.theme, page.appearance_card) == _right(page.language, language)
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
    assert (page.data_dir.text(), page.data_dir.toolTip()) == (
        native("~/data/kresorter"),
        str(data_dir),
    )
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
