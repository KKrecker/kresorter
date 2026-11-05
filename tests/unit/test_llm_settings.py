"""Where Ollama or LM Studio is and which model explains: loopback addresses only, names never
resolved (decisions 0013 and 0019)."""

import socket
from typing import Any

import pytest

from kresorter.llm.failure import ExplanationUnavailable, SettingRefused, Unavailable
from kresorter.llm.settings import (
    DEFAULT_ADDRESS,
    LMSTUDIO_ADDRESS,
    LMSTUDIO_MODEL_VARIABLE,
    LMSTUDIO_PORT,
    LMSTUDIO_URL_VARIABLE,
    SERVER_VARIABLE,
    SERVERS,
    Address,
    Variables,
    address_from,
    installed,
    is_model_name,
    model_from,
    server_from,
    variables,
    with_model,
    with_server,
)


def address(value: str) -> Address:
    return address_from({"KRESORTER_OLLAMA_URL": value})


def test_the_default_address_is_ollamas_on_loopback() -> None:
    # [0013.8]
    assert address_from({}) == DEFAULT_ADDRESS == Address("127.0.0.1", 11434)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://127.0.0.1:11434", Address("127.0.0.1", 11434)),
        ("http://127.0.0.1:11434/", Address("127.0.0.1", 11434)),
        ("http://127.8.9.10:1", Address("127.8.9.10", 1)),
        ("http://127.255.255.254:65535", Address("127.255.255.254", 65535)),
        ("http://localhost:8080", Address("127.0.0.1", 8080)),
        ("http://localhost", Address("127.0.0.1", 11434)),
        ("http://[::1]:11434", Address("::1", 11434)),
        ("http://127.0.0.1", Address("127.0.0.1", 11434)),
    ],
)
def test_accepted_addresses(value: str, expected: Address) -> None:
    # [0013.8]
    assert address(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://127.0.0.1:11434",
        "HTTP://127.0.0.1:11434",
        "file:///run/ollama.sock",
        "ftp://127.0.0.1:11434",
        "data:text/plain,hello",
        "127.0.0.1:11434",
        "http://0.0.0.0:11434",
        "http://[::]:11434",
        "http://[::ffff:127.0.0.1]:11434",
        "http://[0:0:0:0:0:0:0:1]:11434",
        "http://127.1:11434",
        "http://2130706433:11434",
        "http://0x7f.0.0.1:11434",
        "http://127.000.0.1:11434",
        "http://127.0.0.256:11434",
        "http://10.0.0.1:11434",
        "http://192.168.1.2:11434",
        "http://128.0.0.1:11434",
        "http://ollama.local:11434",
        "http://localhost.example.com:11434",
        "http://LOCALHOST:11434",
        "http://user@127.0.0.1:11434",
        "http://127.0.0.1:11434/api",
        "http://127.0.0.1:11434?x=1",
        "http://127.0.0.1:11434#f",
        "http://127.0.0.1:0",
        "http://127.0.0.1:65536",
        "http://127.0.0.1:",
        "",
        " http://127.0.0.1:11434",
        "http://127.0.0.1:11434\n",
    ],
)
def test_refused_addresses(value: str) -> None:
    # [0013.8]
    with pytest.raises(ExplanationUnavailable) as refused:
        address(value)
    assert refused.value.reason is Unavailable.CONFIG
    assert refused.value.detail.startswith(f"KRESORTER_OLLAMA_URL={value!r}: ")


def test_localhost_becomes_an_address_without_a_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    # [0013.8]
    asked: list[str] = []

    def resolver(*args: Any, **kwargs: Any) -> Any:
        asked.append(repr(args))
        raise OSError("no resolver here")

    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
        monkeypatch.setattr(socket, name, resolver)
    assert address("http://localhost:11434") == Address("127.0.0.1", 11434)
    assert asked == []


def test_ollama_host_is_not_read() -> None:
    # [0013.8] OLLAMA_HOST is where the server binds, not where to connect.
    assert address_from({"OLLAMA_HOST": "10.0.0.1:11434"}) == DEFAULT_ADDRESS


@pytest.mark.parametrize(
    ("given", "url"),
    [
        (Address("127.0.0.1", 11434), "http://127.0.0.1:11434"),
        (Address("::1", 8), "http://[::1]:8"),
    ],
)
def test_the_address_as_a_url(given: Address, url: str) -> None:
    # [0013.8]
    assert given.url == url


def test_the_default_model() -> None:
    # [0013.9]
    assert model_from({}) == "llama3.2"


@pytest.mark.parametrize(
    "name", ["llama3.2", "llama3.2:1b", "qwen2.5:7b-instruct", "library/mistral:latest", "x"]
)
def test_accepted_model_names(name: str) -> None:
    # [0013.9]
    assert model_from({"KRESORTER_OLLAMA_MODEL": name}) == name


@pytest.mark.parametrize(
    "name", ["", "-x", ".x", "a b", "a;rm", "a" * 101, "llama3.2\n", "llam\u0430", "a\x1b[2J"]
)
def test_refused_model_names(name: str) -> None:
    # [0013.9]
    with pytest.raises(ExplanationUnavailable) as refused:
        model_from({"KRESORTER_OLLAMA_MODEL": name})
    assert refused.value.reason is Unavailable.CONFIG
    assert refused.value.detail.startswith(f"KRESORTER_OLLAMA_MODEL={name!r}: ")


@pytest.mark.parametrize(
    ("model", "names", "found"),
    [
        ("llama3.2", ["llama3.2:latest"], True),
        ("llama3.2", ["llama3.2"], True),
        ("llama3.2", ["llama3.2:1b"], False),
        ("llama3.2:1b", ["llama3.2:1b"], True),
        ("llama3.2:1b", ["llama3.2:latest"], False),
        ("llama3.2:latest", ["llama3.2:latest"], True),
        ("llama3.2:latest", ["llama3.2"], False),
        ("llama3.2", [], False),
    ],
)
def test_a_model_is_installed_by_its_name_or_latest(
    model: str, names: list[str], found: bool
) -> None:
    # [0013.9]
    assert installed(model, names) is found


# --- the model chosen in the window's settings (decision 0018, item 32) --------------------------


def test_a_model_name_is_one_the_environment_would_take() -> None:
    # [0018.32] [0013.9]
    assert is_model_name("qwen2.5:7b")
    assert is_model_name("library/mistral:latest")
    assert not is_model_name("no model!")
    assert not is_model_name("llam\u0430")
    assert not is_model_name("a" * 101)


def test_the_model_chosen_is_used_unless_the_environment_names_one() -> None:
    # [0018.32] KRESORTER_OLLAMA_MODEL, when set, wins; the rest of the environment as it is.
    url = {"KRESORTER_OLLAMA_URL": "http://127.0.0.1:9"}
    assert model_from(with_model(url, "qwen2.5:3b")) == "qwen2.5:3b"
    assert with_model(url, "qwen2.5:3b")["KRESORTER_OLLAMA_URL"] == "http://127.0.0.1:9"
    assert with_model(url, None) == url
    named = {**url, "KRESORTER_OLLAMA_MODEL": "llama3.2"}
    assert model_from(with_model(named, "qwen2.5:3b")) == "llama3.2"
    assert url == {"KRESORTER_OLLAMA_URL": "http://127.0.0.1:9"}


# --- two local servers, Ollama and LM Studio (decision 0019, items 5-7) --------------------------

LMSTUDIO = {"KRESORTER_LLM_SERVER": "lmstudio"}


def test_the_server_is_ollama_unless_the_environment_names_lm_studio() -> None:
    # [0019.5]
    assert SERVERS == ("ollama", "lmstudio")
    assert SERVER_VARIABLE == "KRESORTER_LLM_SERVER"
    assert server_from({}) == "ollama"
    assert server_from({"KRESORTER_LLM_SERVER": "ollama"}) == "ollama"
    assert server_from(LMSTUDIO) == "lmstudio"


@pytest.mark.parametrize(
    "value", ["", "LMStudio", "lm-studio", "lm studio", "Ollama", " ollama", "llamacpp", "openai"]
)
def test_any_other_server_is_refused(value: str) -> None:
    # [0019.5] a config refusal, which names the variable, before any address is read
    for read in (server_from, address_from, model_from):
        with pytest.raises(SettingRefused) as refused:
            read({"KRESORTER_LLM_SERVER": value, "KRESORTER_OLLAMA_URL": "http://10.0.0.1"})
        assert refused.value.reason is Unavailable.CONFIG
        assert refused.value.name == "KRESORTER_LLM_SERVER"
        assert refused.value.detail.startswith(f"KRESORTER_LLM_SERVER={value!r}: ")


def test_lm_studios_address_is_its_own_on_loopback() -> None:
    # [0019.6] port 1234; Ollama's variable is not read for it, nor its own for Ollama
    assert LMSTUDIO_URL_VARIABLE == "KRESORTER_LMSTUDIO_URL"
    assert LMSTUDIO_PORT == 1234
    assert address_from(LMSTUDIO) == LMSTUDIO_ADDRESS == Address("127.0.0.1", 1234)
    ollama_named = {**LMSTUDIO, "KRESORTER_OLLAMA_URL": "http://127.0.0.1:9"}
    assert address_from(ollama_named) == LMSTUDIO_ADDRESS
    assert address_from({"KRESORTER_LMSTUDIO_URL": "http://127.0.0.1:9"}) == DEFAULT_ADDRESS


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://127.0.0.1:1234", Address("127.0.0.1", 1234)),
        ("http://127.0.0.1:1234/", Address("127.0.0.1", 1234)),
        ("http://localhost", Address("127.0.0.1", 1234)),
        ("http://127.0.0.1", Address("127.0.0.1", 1234)),
        ("http://localhost:8080", Address("127.0.0.1", 8080)),
        ("http://[::1]", Address("::1", 1234)),
        ("http://127.8.9.10:1", Address("127.8.9.10", 1)),
    ],
)
def test_lm_studios_accepted_addresses(value: str, expected: Address) -> None:
    # [0019.6] the form of 0013 item 8, 1234 when the port is left out
    assert address_from({**LMSTUDIO, "KRESORTER_LMSTUDIO_URL": value}) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://127.0.0.1:1234",
        "http://0.0.0.0:1234",
        "http://10.0.0.1:1234",
        "http://example.com:1234",
        "http://127.0.0.1:0",
        "http://127.0.0.1:1234/v1",
        "127.0.0.1:1234",
        "",
    ],
)
def test_lm_studios_refused_addresses(value: str) -> None:
    # [0019.6] the checks of 0013 item 8, which name LM Studio's variable
    with pytest.raises(SettingRefused) as refused:
        address_from({**LMSTUDIO, "KRESORTER_LMSTUDIO_URL": value})
    assert refused.value.reason is Unavailable.CONFIG
    assert refused.value.name == "KRESORTER_LMSTUDIO_URL"
    assert refused.value.detail.startswith(f"KRESORTER_LMSTUDIO_URL={value!r}: ")


def test_lm_studio_has_no_model_unless_one_is_named() -> None:
    # [0019.7] None: the first that LM Studio lists is taken; Ollama's variable is not read
    assert LMSTUDIO_MODEL_VARIABLE == "KRESORTER_LMSTUDIO_MODEL"
    assert model_from(LMSTUDIO) is None
    assert model_from({**LMSTUDIO, "KRESORTER_OLLAMA_MODEL": "qwen2.5:7b"}) is None
    named = {**LMSTUDIO, "KRESORTER_LMSTUDIO_MODEL": "qwen2.5-7b-instruct"}
    assert model_from(named) == "qwen2.5-7b-instruct"
    assert model_from({"KRESORTER_LMSTUDIO_MODEL": "qwen2.5-7b-instruct"}) == "llama3.2"


@pytest.mark.parametrize(
    "name",
    ["qwen2.5-7b-instruct", "qwen2.5-7b-instruct@q4_k_m", "qwen/qwen3-8b", "lmstudio-community/x"],
)
def test_lm_studios_accepted_model_names(name: str) -> None:
    # [0019.7] LM Studio names a quantization after @; the same names for either server
    assert is_model_name(name)
    assert model_from({**LMSTUDIO, "KRESORTER_LMSTUDIO_MODEL": name}) == name
    assert model_from({"KRESORTER_OLLAMA_MODEL": name}) == name


@pytest.mark.parametrize("name", ["", "@q4", "a b", "a@b c", "a" * 101, "qw\u0435n", "a\nb"])
def test_lm_studios_refused_model_names(name: str) -> None:
    # [0019.7]
    with pytest.raises(SettingRefused) as refused:
        model_from({**LMSTUDIO, "KRESORTER_LMSTUDIO_MODEL": name})
    assert refused.value.reason is Unavailable.CONFIG
    assert refused.value.detail.startswith(f"KRESORTER_LMSTUDIO_MODEL={name!r}: ")


def test_the_model_chosen_is_the_servers_unless_the_environment_names_one() -> None:
    # [0019.7] the window's choice, for the server in use: its variable, when set, wins
    chosen = with_model(LMSTUDIO, "qwen2.5-7b-instruct")
    assert chosen == {**LMSTUDIO, "KRESORTER_LMSTUDIO_MODEL": "qwen2.5-7b-instruct"}
    assert model_from(chosen) == "qwen2.5-7b-instruct"
    named = {**LMSTUDIO, "KRESORTER_LMSTUDIO_MODEL": "llama-3.2-1b-instruct"}
    assert with_model(named, "qwen2.5-7b-instruct") == named
    assert with_model(LMSTUDIO, None) == LMSTUDIO
    assert with_model({}, "qwen2.5:3b") == {"KRESORTER_OLLAMA_MODEL": "qwen2.5:3b"}
    refused = {"KRESORTER_LLM_SERVER": "openai"}
    assert with_model(refused, "x") == {**refused, "KRESORTER_OLLAMA_MODEL": "x"}  # still refused
    assert LMSTUDIO == {"KRESORTER_LLM_SERVER": "lmstudio"}


def test_the_server_chosen_is_used_unless_the_environment_names_one() -> None:
    # [0019.5] the window's choice: KRESORTER_LLM_SERVER, when set, wins
    assert with_server({}, "lmstudio") == LMSTUDIO
    assert server_from(with_server({}, "lmstudio")) == "lmstudio"
    assert with_server({"KRESORTER_LLM_SERVER": "ollama"}, "lmstudio") == {
        "KRESORTER_LLM_SERVER": "ollama"
    }
    assert with_server({"KRESORTER_OLLAMA_URL": "http://127.0.0.1:9"}, None) == {
        "KRESORTER_OLLAMA_URL": "http://127.0.0.1:9"
    }


def test_each_servers_variables() -> None:
    # [0019.5] [0019.6] [0019.7] what the console and the window name for each
    assert variables("ollama") == Variables(
        "ollama", "KRESORTER_OLLAMA_URL", "KRESORTER_OLLAMA_MODEL", DEFAULT_ADDRESS, "llama3.2"
    )
    assert variables("lmstudio") == Variables(
        "lmstudio", "KRESORTER_LMSTUDIO_URL", "KRESORTER_LMSTUDIO_MODEL", LMSTUDIO_ADDRESS, None
    )
