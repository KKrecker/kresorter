"""Where Ollama is and which model explains: loopback addresses only, names never resolved."""

import socket
from typing import Any

import pytest

from kresorter.llm.failure import ExplanationUnavailable, Unavailable
from kresorter.llm.settings import (
    DEFAULT_ADDRESS,
    Address,
    address_from,
    installed,
    model_from,
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
