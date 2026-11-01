"""Where Ollama is and which model explains (decision 0013, items 8 and 9).

The address is checked by a pinned expression and by ``ipaddress``, not by a URL parser, and a
name is never resolved: ``localhost`` is ``127.0.0.1`` here, and only an address leaves.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from ipaddress import AddressValueError, IPv4Address, IPv4Network

from safeclean.llm.failure import ExplanationUnavailable, Unavailable

URL_VARIABLE = "SAFECLEAN_OLLAMA_URL"
MODEL_VARIABLE = "SAFECLEAN_OLLAMA_MODEL"
DEFAULT_PORT = 11434
DEFAULT_MODEL = "llama3.2"

_URL = re.compile(
    r"http://(?P<host>localhost|[0-9]{1,3}(?:\.[0-9]{1,3}){3}|\[::1\])(?::(?P<port>[0-9]{1,5}))?/?",
    re.ASCII,
)
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}", re.ASCII)
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


def _refused(name: str, value: str, why: str) -> ExplanationUnavailable:
    return ExplanationUnavailable(Unavailable.CONFIG, f"{name}={value!r}: {why}")


def address_from(env: Mapping[str, str]) -> Address:
    value = env.get(URL_VARIABLE)
    if value is None:
        return DEFAULT_ADDRESS
    match = _URL.fullmatch(value)
    if match is None:
        raise _refused(URL_VARIABLE, value, "not http://HOST[:PORT] with a loopback HOST")
    port = int(match["port"] or DEFAULT_PORT)
    if not 1 <= port <= 65535:
        raise _refused(URL_VARIABLE, value, "the port is not 1-65535")
    host = match["host"]
    if host == "localhost":
        return Address("127.0.0.1", port)
    if host == "[::1]":
        return Address("::1", port)
    try:
        ip = IPv4Address(host)
    except AddressValueError:
        raise _refused(URL_VARIABLE, value, "not an IPv4 address") from None
    if ip not in _LOOPBACK:
        raise _refused(URL_VARIABLE, value, "not a loopback address")
    return Address(str(ip), port)


def model_from(env: Mapping[str, str]) -> str:
    value = env.get(MODEL_VARIABLE, DEFAULT_MODEL)
    if _MODEL.fullmatch(value) is None:
        raise _refused(MODEL_VARIABLE, value, "not a model name")
    return value


def installed(model: str, names: Iterable[str]) -> bool:
    """Ollama lists ``llama3.2`` as ``llama3.2:latest``; a tagged name must match exactly."""
    wanted = {model} if ":" in model else {model, f"{model}:latest"}
    return not wanted.isdisjoint(names)
