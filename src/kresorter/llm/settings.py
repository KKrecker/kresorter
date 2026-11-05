"""Which local server explains, where it is and which model (decisions 0013, items 8 and 9,
and 0019, items 5-7): Ollama, unless ``KRESORTER_LLM_SERVER`` names LM Studio.

The address is checked by a pinned expression and by ``ipaddress``, not by a URL parser, and a
name is never resolved: ``localhost`` is ``127.0.0.1`` here, and only an address leaves.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from ipaddress import AddressValueError, IPv4Address, IPv4Network
from typing import Final, Literal

from kresorter.llm.failure import SettingRefused

Server = Literal["ollama", "lmstudio"]
SERVERS: Final[tuple[Server, ...]] = ("ollama", "lmstudio")
SERVER_NAMES: Final[dict[Server, str]] = {"ollama": "Ollama", "lmstudio": "LM Studio"}
SERVER_VARIABLE = "KRESORTER_LLM_SERVER"
URL_VARIABLE = "KRESORTER_OLLAMA_URL"
MODEL_VARIABLE = "KRESORTER_OLLAMA_MODEL"
DEFAULT_PORT = 11434
DEFAULT_MODEL = "llama3.2"
LMSTUDIO_URL_VARIABLE = "KRESORTER_LMSTUDIO_URL"
LMSTUDIO_MODEL_VARIABLE = "KRESORTER_LMSTUDIO_MODEL"
LMSTUDIO_PORT = 1234

_URL = re.compile(
    r"http://(?P<host>localhost|[0-9]{1,3}(?:\.[0-9]{1,3}){3}|\[::1\])(?::(?P<port>[0-9]{1,5}))?/?",
    re.ASCII,
)
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,99}", re.ASCII)
_LOOPBACK = IPv4Network("127.0.0.0/8")


@dataclass(frozen=True)
class Address:
    """Ollama's address: an IP address on loopback, never a name, and a port."""

    host: str
    port: int

    @property
    def ipv6(self) -> bool:
        return ":" in self.host

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if self.ipv6 else self.host
        return f"http://{host}:{self.port}"


DEFAULT_ADDRESS = Address("127.0.0.1", DEFAULT_PORT)
LMSTUDIO_ADDRESS = Address("127.0.0.1", LMSTUDIO_PORT)


@dataclass(frozen=True)
class Variables:
    """A server's settings: the variables of its address and model, and their defaults; LM
    Studio's model, when none is named, is the first it lists (decision 0019, item 7)."""

    server: Server
    url: str
    model: str
    address: Address
    default_model: str | None


OLLAMA = Variables("ollama", URL_VARIABLE, MODEL_VARIABLE, DEFAULT_ADDRESS, DEFAULT_MODEL)
LMSTUDIO = Variables(
    "lmstudio", LMSTUDIO_URL_VARIABLE, LMSTUDIO_MODEL_VARIABLE, LMSTUDIO_ADDRESS, None
)


def variables(server: Server) -> Variables:
    return LMSTUDIO if server == "lmstudio" else OLLAMA


def server_from(env: Mapping[str, str]) -> Server:
    """``ollama`` when ``KRESORTER_LLM_SERVER`` is unset, else what it names, one of two."""
    value = env.get(SERVER_VARIABLE, "ollama")
    for server in SERVERS:
        if value == server:
            return server
    raise SettingRefused(SERVER_VARIABLE, value, "not ollama or lmstudio")


def address_from(env: Mapping[str, str]) -> Address:
    """The address of the server ``env`` names, from its own variable."""
    named = variables(server_from(env))
    value = env.get(named.url)
    if value is None:
        return named.address
    match = _URL.fullmatch(value)
    if match is None:
        raise SettingRefused(named.url, value, "not http://HOST[:PORT] with a loopback HOST")
    port = int(match["port"] or named.address.port)
    if not 1 <= port <= 65535:
        raise SettingRefused(named.url, value, "the port is not 1-65535")
    host = match["host"]
    if host == "localhost":
        return Address("127.0.0.1", port)
    if host == "[::1]":
        return Address("::1", port)
    try:
        ip = IPv4Address(host)
    except AddressValueError:
        raise SettingRefused(named.url, value, "not an IPv4 address") from None
    if ip not in _LOOPBACK:
        raise SettingRefused(named.url, value, "not a loopback address")
    return Address(str(ip), port)


def is_model_name(value: str) -> bool:
    """A name item 9 accepts: the window's choice is held to it too (decision 0018, item 32)."""
    return _MODEL.fullmatch(value) is not None


def model_from(env: Mapping[str, str]) -> str | None:
    """The model of the server ``env`` names, from its own variable: Ollama's is ``llama3.2``
    when unset, LM Studio's ``None``."""
    named = variables(server_from(env))
    value = env.get(named.model, named.default_model)
    if value is not None and not is_model_name(value):
        raise SettingRefused(named.model, value, "not a model name")
    return value


def server_in(env: Mapping[str, str]) -> Server:
    """The server ``env`` names; Ollama when it names none, or one refused (``server_from``
    says why)."""
    return "lmstudio" if env.get(SERVER_VARIABLE) == "lmstudio" else "ollama"


def with_model(env: Mapping[str, str], model: str | None) -> Mapping[str, str]:
    """``env`` with ``model`` as its server's model unless it names one: the variable, when
    set, wins (decision 0018, item 32). A server refused takes Ollama's, refused all the same.
    ``env`` itself is not changed."""
    variable = variables(server_in(env)).model
    if model is None or variable in env:
        return env
    return {**env, variable: model}


def with_server(env: Mapping[str, str], server: Server | None) -> Mapping[str, str]:
    """``env`` with ``server`` unless it names one: ``KRESORTER_LLM_SERVER``, when set, wins
    (decision 0019, item 5). ``env`` itself is not changed."""
    if server is None or SERVER_VARIABLE in env:
        return env
    return {**env, SERVER_VARIABLE: server}


def installed(model: str, names: Iterable[str]) -> bool:
    """Ollama lists ``llama3.2`` as ``llama3.2:latest``; a tagged name must match exactly."""
    wanted = {model} if ":" in model else {model, f"{model}:latest"}
    return not wanted.isdisjoint(names)
