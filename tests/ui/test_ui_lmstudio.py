"""LM Studio in the window (decision 0019, items 11-13).

The Settings card is Local AI, with a choice of server, Ollama or LM Studio, saved as
``server``: a change forgets the model chosen, which is the chosen server's, and runs Check,
whose lines are those of ``kresorter llm status``. The address, the model's choice, the
recommendation and the steps are the chosen server's; ``KRESORTER_LLM_SERVER``, when set, wins,
a note says so and the choice is disabled. The Overview's card names the server, and an
explanation's note says via LM Studio when LM Studio answered.
"""

import io
import json
import socket
from collections.abc import Mapping
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFrame, QLabel
from pytestqt.qtbot import QtBot

from kresorter.cli_llm import run_status
from kresorter.llm.machine import GIB, Machine
from kresorter.llm.settings import (
    LMSTUDIO_MODEL_VARIABLE,
    LMSTUDIO_URL_VARIABLE,
    MODEL_VARIABLE,
    SERVER_VARIABLE,
    URL_VARIABLE,
    Address,
)
from kresorter.ui.i18n import Language
from kresorter.ui.settings import Settings
from kresorter.ui.settings_page import SettingsPage
from kresorter.ui.window import Window
from support.lmstudio import CHAT, EMBEDDING, LISTED, MODEL, MODELS, completed, models
from support.ollama import TAGS, VERSION, Answer, ScriptedOllama
from support.window import environment, junk_tree, make_window, scanned, settled, wait_idle

OLLAMA_CHECKS = [("GET", "/api/version"), ("GET", "/api/tags")]
FIRST = "the first model LM Studio lists"
AVAILABLE = (
    "Explanations are available: Explain (local AI) on a finding, an autostart entry or a file"
    " that stays in place."
)
SETUP = [
    "Explanations are unavailable; kresorter works as usual without them.",
    "To set them up (kresorter installs nothing itself):",
]
INSTALL = (
    "Install LM Studio from https://lmstudio.ai, download a model and start its server"
    " (Developer, Start Server)."
)
AGAIN = "Check again."
SETTINGS = (
    "Settings, from the environment the window started in: KRESORTER_LLM_SERVER (ollama or"
    " lmstudio, default ollama), KRESORTER_LMSTUDIO_URL (a loopback address, default"
    " http://127.0.0.1:1234) and KRESORTER_LMSTUDIO_MODEL (default the first model LM Studio"
    " lists)."
)
OLLAMA_SETTINGS = (
    "Settings, from the environment the window started in: KRESORTER_LLM_SERVER (ollama or"
    " lmstudio, default ollama), KRESORTER_OLLAMA_URL (a loopback address, default"
    " http://127.0.0.1:11434) and KRESORTER_OLLAMA_MODEL (default llama3.2)."
)
SERVER_NOTE = (
    "KRESORTER_LLM_SERVER sets the server: {}. The server chosen here applies once it is unset."
)
ANSWER = "A thumbnail cache Windows makes again when it needs it."
MACHINE = Machine(16 * GIB, 8)


def _window(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    llm_env: Mapping[str, str] | None = None,
    *,
    language: Language = "en",
    machine: Machine = MACHINE,
) -> Window:
    """The window on its Settings page."""
    env = environment(tmp_path, zone, data_dir, llm_env=llm_env, machine=machine)
    window = make_window(qtbot, env, language=language)
    window.show_page("settings")
    wait_idle(qtbot, window)
    return window


def _check(qtbot: QtBot, window: Window) -> SettingsPage:
    page = window.settings
    page.check_button.click()
    wait_idle(qtbot, window)
    return page


def _choose(qtbot: QtBot, window: Window, index: int) -> SettingsPage:
    """The server of ``index`` chosen, and whatever that runs done."""
    page = window.settings
    page.server.setCurrentIndex(index)
    wait_idle(qtbot, window)
    return page


def _lines(page: SettingsPage) -> list[str]:
    """What the check found: the server, the model, then the rest."""
    return [*(found.text() for found in page.found), *page.check.text().splitlines()]


def _dots(page: SettingsPage) -> list[object]:
    return [found.dot.property("dot") for found in page.found]


def _servers(page: SettingsPage) -> list[str]:
    return [page.server.itemText(index) for index in range(page.server.count())]


def _models(page: SettingsPage) -> list[str]:
    return [page.model.itemText(index) for index in range(page.model.count())]


def _titles(card: QFrame) -> list[str]:
    return [
        label.text()
        for label in card.findChildren(QLabel)
        if label.property("role") == "card-title"
    ]


def _saved(data_dir: Path) -> object:
    return json.loads((data_dir / "settings.json").read_bytes())


def _status(env: Mapping[str, str]) -> list[str]:
    """What 'kresorter llm status' says with ``env``."""
    out = io.StringIO()
    run_status(env, out)
    return out.getvalue().splitlines()


def _steps(*steps: str) -> list[str]:
    return [f"{n}. {step}" for n, step in enumerate([*steps, AGAIN], start=1)]


def _closed() -> Address:
    """A loopback port nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return Address("127.0.0.1", port)


def _card(window: Window) -> str:
    """The main line of the Overview's card for the local AI."""
    return window.overview.services["ai"].main.text()


# --- the choice of server ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "title", "server"),
    [("en", "Local AI", "Server"), ("ru", "Локальный ИИ", "Сервер")],
)
def test_the_card_is_local_ai_with_a_choice_of_ollama_or_lm_studio(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    language: Language,
    title: str,
    server: str,
) -> None:
    # [0019.12] Ollama when none is chosen; the choice labelled, on the card.
    window = _window(qtbot, tmp_path, zone, data_dir, language=language)
    page = window.settings
    assert _titles(page.ai_card) == [title]
    assert _servers(page) == ["Ollama", "LM Studio"]
    assert page.server.currentIndex() == 0
    assert page.server.isEnabled()
    assert page.server.accessibleName() == server
    assert (page.server_title.text(), page.server_title.buddy()) == (server, page.server)
    assert page.ai_card.isAncestorOf(page.server)
    assert page.server_note.isHidden()
    assert not data_dir.exists()


def test_lm_studio_chosen_is_saved_forgets_the_model_and_runs_check(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.12] [0019.7] The model chosen was Ollama's; Check asks LM Studio alone, which
    # takes the first model it lists to chat with.
    settled(data_dir, model="qwen2.5:3b")
    with ScriptedOllama(models(EMBEDDING, MODEL)) as lmstudio:
        url = lmstudio.address.url
        window = _window(qtbot, tmp_path, zone, data_dir, {LMSTUDIO_URL_VARIABLE: url})
        page = _choose(qtbot, window, 1)
        asked = lmstudio.paths()

    assert _saved(data_dir) == {
        "language": "system",
        "include_machine": False,
        "skipped_zones": [],
        "theme": "system",
        "server": "lmstudio",
    }
    assert page.current == Settings(server="lmstudio")
    assert page.result.text() == "Saved."
    assert asked == [LISTED]
    assert _lines(page) == [f"LM Studio: running at {url}", f"Model: {MODEL}: available", AVAILABLE]
    assert _dots(page) == ["safe", "safe"]
    assert page.address.text() == f"Address: {url} · Model: {FIRST}"
    assert (_models(page), page.model.currentIndex()) == ([MODEL], -1)
    assert page.server.currentIndex() == 1
    assert window.sidebar.ai.text() == "AI explanations: LM Studio"


def test_ollama_chosen_again_is_left_out_of_the_file_and_checked(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.12] The model chosen was LM Studio's; Ollama's own is in use again.
    settled(data_dir, server="lmstudio", model=MODEL)
    with ScriptedOllama(VERSION, TAGS) as ollama:
        url = ollama.address.url
        window = _window(qtbot, tmp_path, zone, data_dir, {URL_VARIABLE: url})
        assert window.settings.server.currentIndex() == 1
        assert window.settings.address.text() == f"Address: http://127.0.0.1:1234 · Model: {MODEL}"
        assert window.sidebar.ai.text() == f"AI explanations: {MODEL}"
        page = _choose(qtbot, window, 0)
        asked = ollama.paths()

    saved = _saved(data_dir)
    assert isinstance(saved, dict)
    assert ("server" in saved, "model" in saved) == (False, False)
    assert page.current == Settings()
    assert asked == OLLAMA_CHECKS
    assert _lines(page)[:2] == [
        f"Ollama: running at {url} (version 0.6.2)",
        "Model: llama3.2: installed",
    ]
    assert page.address.text() == f"Address: {url} · Model: llama3.2"
    assert window.sidebar.ai.text() == "AI explanations: llama3.2"


def test_a_server_that_cannot_be_saved_is_not_used(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.12] [0014.35] Nothing changes, and nothing is asked.
    data_dir.parent.mkdir(parents=True)
    data_dir.write_bytes(b"not a directory")
    with ScriptedOllama(MODELS) as lmstudio:
        env = {LMSTUDIO_URL_VARIABLE: lmstudio.address.url}
        page = _choose(qtbot, _window(qtbot, tmp_path, zone, data_dir, env), 1)
        connections = lmstudio.connections

    assert page.result.text().startswith("Not saved: The data folder cannot be used: ")
    assert page.server.currentIndex() == 0
    assert page.current == Settings()
    assert connections == 0
    assert page.address.text() == "Address: http://127.0.0.1:11434 · Model: llama3.2"
    assert [found.isHidden() for found in page.found] == [True, True]


def test_the_environment_s_server_wins_and_the_card_says_so(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.12] [0019.5] Before a check too; the choice cannot change it, and the model chosen
    # for Ollama is not LM Studio's.
    settled(data_dir, model="qwen2.5:3b")
    with ScriptedOllama(MODELS) as lmstudio:
        url = lmstudio.address.url
        env = {SERVER_VARIABLE: "lmstudio", LMSTUDIO_URL_VARIABLE: url}
        window = _window(qtbot, tmp_path, zone, data_dir, env)
        page = window.settings
        assert page.server_note.text() == SERVER_NOTE.format("lmstudio")
        assert not page.server_note.isHidden()
        assert (page.server.currentIndex(), page.server.isEnabled()) == (1, False)
        assert page.address.text() == f"Address: {url} · Model: {FIRST}"
        _check(qtbot, window)
        asked = lmstudio.paths()

    assert asked == [LISTED]
    assert _lines(page)[:2] == [f"LM Studio: running at {url}", f"Model: {MODEL}: available"]
    assert not page.server.isEnabled()
    assert page.current == Settings(model="qwen2.5:3b")
    assert window.sidebar.ai.text() == "AI explanations: LM Studio"


def test_a_server_the_environment_names_wrongly_is_refused(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.12] [0019.5] As 'kresorter llm status': refused, and nothing asked.
    env = {SERVER_VARIABLE: "LM Studio"}
    window = _window(qtbot, tmp_path, zone, data_dir, env)
    page = window.settings
    assert page.server_note.text() == SERVER_NOTE.format("LM Studio")
    assert not page.server.isEnabled()
    assert window.sidebar.ai.text() == "AI explanations: KRESORTER_LLM_SERVER is refused"
    assert _card(window) == "KRESORTER_LLM_SERVER is refused"
    shown = _lines(_check(qtbot, window))

    assert shown[:2] == _status(env)[:2]
    assert shown == [
        "Local AI: refused setting KRESORTER_LLM_SERVER='LM Studio' (not ollama or lmstudio)",
        "Model: not checked",
        *SETUP,
        *_steps(),
        OLLAMA_SETTINGS,
    ]
    assert _dots(page) == ["review", "review"]


# --- the model -----------------------------------------------------------------------------------


def test_a_model_chosen_for_lm_studio_is_saved_and_checked(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.12] [0019.7] The models LM Studio lists to chat with; the one chosen is its own.
    settled(data_dir, server="lmstudio")
    listed = models(EMBEDDING, "qwen2.5-3b-instruct", MODEL)
    with ScriptedOllama(listed, listed) as lmstudio:
        url = lmstudio.address.url
        window = _window(qtbot, tmp_path, zone, data_dir, {LMSTUDIO_URL_VARIABLE: url})
        page = _check(qtbot, window)
        first = _lines(page)[1]
        assert (_models(page), page.model.currentIndex()) == (["qwen2.5-3b-instruct", MODEL], -1)
        page.model.setCurrentIndex(1)
        wait_idle(qtbot, window)
        asked = lmstudio.paths()

    assert first == "Model: qwen2.5-3b-instruct: available"
    saved = _saved(data_dir)
    assert isinstance(saved, dict)
    assert (saved["server"], saved["model"]) == ("lmstudio", MODEL)
    assert page.current == Settings(model=MODEL, server="lmstudio")
    assert asked == [LISTED, LISTED]
    assert page.address.text() == f"Address: {url} · Model: {MODEL}"
    assert _lines(page)[1] == f"Model: {MODEL}: available"
    assert page.model.currentIndex() == 1
    assert window.sidebar.ai.text() == f"AI explanations: {MODEL}"
    assert _card(window) == f"LM Studio · Model: {MODEL}"


def test_lm_studio_s_model_variable_wins_and_ollama_s_is_not_its(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.12] [0019.7] The note and the disabled choice are the server's own variable's.
    named = {SERVER_VARIABLE: "lmstudio", MODEL_VARIABLE: "llama3.2"}
    env = {**named, LMSTUDIO_MODEL_VARIABLE: "qwen2.5-3b-instruct"}
    page = _window(qtbot, tmp_path, zone, data_dir, env).settings
    assert page.model_note.text() == (
        "KRESORTER_LMSTUDIO_MODEL sets the model: qwen2.5-3b-instruct. The model chosen here"
        " applies once it is unset."
    )
    assert not page.model_note.isHidden()
    assert not page.model.isEnabled()
    assert page.address.text() == "Address: http://127.0.0.1:1234 · Model: qwen2.5-3b-instruct"
    other = _window(qtbot, tmp_path, zone, data_dir, named).settings
    assert other.model_note.isHidden()
    assert other.model.isEnabled()
    assert other.address.text() == f"Address: http://127.0.0.1:1234 · Model: {FIRST}"


def test_a_change_of_server_shows_its_own_model_variable_and_recommendation(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.12] [0019.13] KRESORTER_OLLAMA_MODEL is Ollama's alone.
    address = _closed()
    env = {MODEL_VARIABLE: "llama3.2", LMSTUDIO_URL_VARIABLE: address.url}
    window = _window(qtbot, tmp_path, zone, data_dir, env)
    page = window.settings
    assert not page.model_note.isHidden()
    assert not page.model.isEnabled()
    assert page.recommended.text().endswith(
        "To get it: ollama pull qwen2.5:7b (kresorter installs nothing itself)."
    )
    _choose(qtbot, window, 1)

    assert page.model_note.isHidden()
    assert page.model.isEnabled()
    assert page.recommended.text().endswith(
        "To get it: find qwen2.5-7b-instruct in LM Studio's Discover tab and download it"
        " (kresorter installs nothing itself)."
    )
    assert _lines(page)[0].startswith(f"LM Studio: not reachable at {address.url} (")


# --- the check -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("listed", "model", "lines", "dots"),
    [
        (MODELS, None, [f"Model: {MODEL}: available", AVAILABLE], ["safe", "safe"]),
        (
            models(EMBEDDING),
            None,
            ["Model: none listed", *SETUP, *_steps(INSTALL), SETTINGS],
            ["safe", "review"],
        ),
        (
            MODELS,
            "qwen2.5-14b-instruct",
            [
                "Model: qwen2.5-14b-instruct: not available",
                *SETUP,
                *_steps("Download the model in LM Studio: qwen2.5-14b-instruct"),
                SETTINGS,
            ],
            ["safe", "review"],
        ),
    ],
)
def test_the_check_of_lm_studio_shows_the_lines_of_llm_status(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    listed: Answer,
    model: str | None,
    lines: list[str],
    dots: list[str],
) -> None:
    # [0019.12] [0019.10] Its steps and its settings are LM Studio's.
    settled(data_dir, server="lmstudio")
    with ScriptedOllama(listed, listed) as lmstudio:  # the window's check, then the CLI's
        url = lmstudio.address.url
        named = {} if model is None else {LMSTUDIO_MODEL_VARIABLE: model}
        env = {LMSTUDIO_URL_VARIABLE: url, **named}
        page = _check(qtbot, _window(qtbot, tmp_path, zone, data_dir, env))
        cli = _status({**env, SERVER_VARIABLE: "lmstudio"})

    shown = _lines(page)
    assert shown[:2] == cli[:2]
    assert shown == [f"LM Studio: running at {url}", *lines]
    assert _dots(page) == dots


def test_lm_studio_that_is_not_there_is_named_with_its_address(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.12] [0019.9] Ollama at its address does not answer as LM Studio; nothing there is
    # not reachable. Installing and starting it is the step either way.
    settled(data_dir, server="lmstudio")
    rest = ["Model: not checked", *SETUP, *_steps(INSTALL), SETTINGS]
    with ScriptedOllama(VERSION, VERSION) as ollama:
        env = {LMSTUDIO_URL_VARIABLE: ollama.address.url}
        page = _check(qtbot, _window(qtbot, tmp_path, zone, data_dir, env))
        other = _lines(page)
        cli = _status({**env, SERVER_VARIABLE: "lmstudio"})
    closed = _closed()
    env = {LMSTUDIO_URL_VARIABLE: closed.url}
    window = _window(qtbot, tmp_path, zone, data_dir, env)
    shown = _lines(_check(qtbot, window))

    assert other[:2] == cli[:2]
    assert other[0].startswith(f"LM Studio: {ollama.address.url} does not answer as LM Studio (")
    assert other[1:] == rest
    assert shown[:2] == _status({**env, SERVER_VARIABLE: "lmstudio"})[:2]
    assert shown[0].startswith(f"LM Studio: not reachable at {closed.url} (")
    assert shown[1:] == rest
    assert _dots(window.settings) == ["review", "review"]


def test_lm_studio_s_card_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.12] [0019.13]
    settled(data_dir, server="lmstudio")
    with ScriptedOllama(MODELS, models(EMBEDDING)) as lmstudio:
        url = lmstudio.address.url
        env = {LMSTUDIO_URL_VARIABLE: url}
        window = _window(qtbot, tmp_path, zone, data_dir, env, language="ru")
        page = _check(qtbot, window)
        available = _lines(page)
        _check(qtbot, window)

    assert page.address.text() == f"Адрес: {url} · Модель: первая модель в списке LM Studio"
    assert available[:2] == [f"LM Studio: работает по адресу {url}", f"Модель: {MODEL}: доступна"]
    assert _lines(page) == [
        f"LM Studio: работает по адресу {url}",
        "Модель: ни одной в списке",
        "Объяснения недоступны; kresorter работает без них как обычно.",
        "Как их настроить (kresorter сам ничего не устанавливает):",
        "1. Установите LM Studio (https://lmstudio.ai), скачайте модель и запустите её сервер"
        " (Developer, Start Server).",
        "2. Проверьте снова.",
        "Настройки берутся из окружения, в котором запущено окно: KRESORTER_LLM_SERVER (ollama"
        " или lmstudio, по умолчанию ollama), KRESORTER_LMSTUDIO_URL (адрес loopback, по"
        " умолчанию http://127.0.0.1:1234) и KRESORTER_LMSTUDIO_MODEL (по умолчанию первая"
        " модель в списке LM Studio).",
    ]
    assert page.recommended.text().endswith(
        ": qwen2.5-7b-instruct; Qwen 2.5 пишет и по-русски, и по-английски. Чтобы получить её:"
        " найдите qwen2.5-7b-instruct на вкладке Discover в LM Studio и скачайте её (kresorter"
        " сам ничего не устанавливает)."
    )
    assert window.sidebar.ai.text() == "Объяснения ИИ: LM Studio"


def test_a_model_lm_studio_has_not_and_the_server_s_note_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.12]
    with ScriptedOllama(MODELS) as lmstudio:
        url = lmstudio.address.url
        env = {SERVER_VARIABLE: "lmstudio", LMSTUDIO_URL_VARIABLE: url}
        env[LMSTUDIO_MODEL_VARIABLE] = "qwen2.5-14b-instruct"
        window = _window(qtbot, tmp_path, zone, data_dir, env, language="ru")
        page = _check(qtbot, window)

    assert page.server_note.text() == (
        "KRESORTER_LLM_SERVER задаёт сервер: lmstudio. Сервер, выбранный здесь, применится, когда"
        " переменная не задана."
    )
    assert _lines(page)[1] == "Модель: qwen2.5-14b-instruct: недоступна"
    assert _lines(page)[4] == "1. Скачайте модель в LM Studio: qwen2.5-14b-instruct"


# --- the recommendation [0019.13] ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("memory", "processors", "model"),
    [
        (4 * GIB, 8, "qwen2.5-1.5b-instruct"),
        (16 * GIB, 8, "qwen2.5-7b-instruct"),
        (32 * GIB, 16, "qwen2.5-14b-instruct"),
    ],
)
def test_the_recommendation_for_lm_studio_is_the_same_model_as_lm_studio_names_it(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    memory: int,
    processors: int,
    model: str,
) -> None:
    # [0019.13] Found in its Discover tab; kresorter installs nothing.
    settled(data_dir, server="lmstudio")
    machine = Machine(memory, processors)
    window = _window(qtbot, tmp_path, zone, data_dir, machine=machine)
    size = window.translator.size(memory)
    assert window.settings.recommended.text() == (
        f"Recommended for this computer ({size} of memory, {processors} processors): {model};"
        " Qwen 2.5 writes Russian as well as English. To get it: find"
        f" {model} in LM Studio's Discover tab and download it (kresorter installs nothing"
        " itself)."
    )


# --- the Overview and the explanations -----------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "env", "language", "main"),
    [
        ({}, {}, "en", "Ollama · Model: llama3.2"),
        ({"server": "lmstudio"}, {}, "en", "LM Studio · Model: the first it lists"),
        ({"server": "lmstudio", "model": MODEL}, {}, "en", f"LM Studio · Model: {MODEL}"),
        (
            {},
            {SERVER_VARIABLE: "lmstudio", LMSTUDIO_MODEL_VARIABLE: MODEL},
            "en",
            f"LM Studio · Model: {MODEL}",
        ),
        ({}, {}, "ru", "Ollama · Модель: llama3.2"),
        ({"server": "lmstudio"}, {}, "ru", "LM Studio · Модель: первая в списке"),
    ],
)
def test_the_overview_s_card_names_the_server(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    values: dict[str, str],
    env: dict[str, str],
    language: Language,
    main: str,
) -> None:
    # [0019.12] Before any check: the card asks nothing.
    settled(data_dir, **values)
    window = make_window(
        qtbot, environment(tmp_path, zone, data_dir, llm_env=env), language=language
    )
    assert _card(window) == main


@pytest.mark.parametrize(
    ("language", "note"),
    [
        ("en", f"{MODEL} via LM Studio · may be wrong"),
        ("ru", f"{MODEL} через LM Studio · может ошибаться"),
    ],
)
def test_an_explanation_lm_studio_gave_says_so(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, language: Language, note: str
) -> None:
    # [0019.11] [0019.12] The server chosen in Settings is the one asked.
    settled(data_dir, server="lmstudio")
    tree = junk_tree(zone)
    with ScriptedOllama(MODELS, completed(ANSWER)) as lmstudio:
        env = environment(
            tmp_path, zone, data_dir, llm_env={LMSTUDIO_URL_VARIABLE: lmstudio.address.url}
        )
        window = make_window(qtbot, env, language=language)
        page = window.findings
        scanned(qtbot, window)
        page.tree.setCurrentItem(page.item(tree["m"]))
        page.explain.button.click()
        wait_idle(qtbot, window)
        asked = lmstudio.paths()

    assert asked == [LISTED, CHAT]
    assert (page.explain.answer.text(), page.explain.note.text()) == (ANSWER, note)


def test_no_explanation_when_lm_studio_is_not_running_says_the_local_ai(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0019.11] Its reason names the local AI, not Ollama.
    settled(data_dir, server="lmstudio")
    tree = junk_tree(zone)
    env = {LMSTUDIO_URL_VARIABLE: _closed().url}
    window = make_window(qtbot, environment(tmp_path, zone, data_dir, llm_env=env))
    page = window.findings
    scanned(qtbot, window)
    page.tree.setCurrentItem(page.item(tree["m"]))
    page.explain.button.click()
    wait_idle(qtbot, window)

    assert page.explain.answer.text() == ""
    assert page.explain.note.text().startswith("No explanation: The local AI is not running (")
