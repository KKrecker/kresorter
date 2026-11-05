"""The Overview's card for the local AI (decision 0018, items 34 and 35): the model in use, and
whether the last Check found it available, unavailable, or that none ran yet; a click opens
Settings. The card asks nothing of Ollama (0013 item 1): only Check does."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from kresorter.llm.settings import MODEL_VARIABLE, URL_VARIABLE
from kresorter.ui.window import Window
from support.ollama import TAGS, VERSION, ScriptedOllama, as_json
from support.window import environment, make_window, settled, wait_idle

CHECKS = [("GET", "/api/version"), ("GET", "/api/tags")]
NOT_YET = "Not checked yet; Check is in Settings"


def _card(window: Window) -> tuple[str, str, str]:
    card = window.overview.services["ai"]
    return card.name.text(), card.main.text(), card.note.text()


def _check(qtbot: QtBot, window: Window) -> None:
    window.show_page("settings")
    window.settings.check_button.click()
    wait_idle(qtbot, window)


def test_the_card_names_the_model_in_use_before_any_check(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.35] [0018.34] And asks Ollama nothing.
    with ScriptedOllama(VERSION, TAGS) as ollama:
        env = {URL_VARIABLE: ollama.address.url}
        window = make_window(qtbot, environment(tmp_path, zone, data_dir, llm_env=env))
        wait_idle(qtbot, window)
        asked = ollama.paths()

    assert _card(window) == ("Local AI", "Ollama · Model: llama3.2", NOT_YET)
    assert asked == []
    card = window.overview.services["ai"]
    assert card.accessibleName() == "Local AI"
    assert card.icon.name == "sparkles"


def test_after_a_check_the_card_says_what_it_found(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.35] Available, then unavailable: the last check is the one said.
    missing = as_json({"models": [{"name": "qwen2.5:3b"}]})
    with ScriptedOllama(VERSION, TAGS, VERSION, missing) as ollama:
        env = {URL_VARIABLE: ollama.address.url}
        window = make_window(qtbot, environment(tmp_path, zone, data_dir, llm_env=env))
        _check(qtbot, window)
        available = _card(window)
        _check(qtbot, window)
        asked = ollama.paths()

    assert available == ("Local AI", "Ollama · Model: llama3.2", "Available at the last check")
    assert _card(window) == (
        "Local AI",
        "Ollama · Model: llama3.2",
        "Unavailable at the last check",
    )
    assert asked == [*CHECKS, *CHECKS]


def test_the_card_names_the_model_chosen_in_settings(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.34] [0018.32] A model chosen again is not checked yet.
    settled(data_dir, model="qwen2.5:3b")
    listed = as_json({"models": [{"name": "qwen2.5:3b"}, {"name": "llama3.2:latest"}]})
    with ScriptedOllama(VERSION, listed, VERSION, as_json({}, status=500)) as ollama:
        env = {URL_VARIABLE: ollama.address.url}
        window = make_window(qtbot, environment(tmp_path, zone, data_dir, llm_env=env))
        assert _card(window)[1:] == ("Ollama · Model: qwen2.5:3b", NOT_YET)
        _check(qtbot, window)
        window.settings.model.setCurrentIndex(1)
        chosen = _card(window)
        wait_idle(qtbot, window)

    assert chosen[1:] == ("Ollama · Model: llama3.2:latest", NOT_YET)
    assert _card(window)[1:] == ("Ollama · Model: llama3.2:latest", "Unavailable at the last check")


def test_a_model_the_environment_names_wrongly_is_said_refused(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.35] [0013.9]
    env = {MODEL_VARIABLE: "no model!"}
    window = make_window(qtbot, environment(tmp_path, zone, data_dir, llm_env=env))
    assert _card(window)[1:] == ("KRESORTER_OLLAMA_MODEL is refused", NOT_YET)


def test_the_card_in_russian(qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path) -> None:
    # [0018.35]
    with ScriptedOllama(VERSION, TAGS) as ollama:
        env = {URL_VARIABLE: ollama.address.url}
        window = make_window(
            qtbot, environment(tmp_path, zone, data_dir, llm_env=env), language="ru"
        )
        before = _card(window)
        _check(qtbot, window)

    assert before == (
        "Локальный ИИ",
        "Ollama · Модель: llama3.2",
        "Ещё не проверялась; проверка — в настройках",
    )
    assert _card(window)[2] == "Доступна по последней проверке"
    refused = {MODEL_VARIABLE: "no model!"}
    other = make_window(
        qtbot, environment(tmp_path, zone, data_dir, llm_env=refused), language="ru"
    )
    assert _card(other)[1] == "Значение KRESORTER_OLLAMA_MODEL отклонено"


def test_the_card_opens_settings_from_the_keyboard_too(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0018.35] [0014.18]
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    card = window.overview.services["ai"]
    assert card.focusPolicy() & Qt.FocusPolicy.TabFocus
    QTest.keyClick(card, Qt.Key.Key_Return)
    assert window.pages.currentWidget() is window.settings
