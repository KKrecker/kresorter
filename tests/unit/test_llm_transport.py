"""The transport to Ollama, against a real server on loopback (decision 0013, items 10, 12).

No resolver, no proxy, no redirect; one deadline for connecting, sending and every read; an
answer and a request of bounded size. Deadlines here are short; the defaults are pinned once.
A timeout may come a little late on a busy machine, never early.
"""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import pytest

from safeclean.llm.failure import ExplanationUnavailable, Unavailable
from safeclean.llm.settings import Address, address_from
from safeclean.llm.transport import LIMITS, Answer, Limits, request
from support.ollama import (
    ScriptedOllama,
    after,
    as_json,
    body,
    chunked,
    drip,
    endless,
    head,
    held_queue,
    never_read,
    phases,
    raw,
    redirect,
    silence,
    until_closed,
)

SRC = Path(__file__).resolve().parents[2] / "src"
PROXY_VARIABLES = [
    case(name) for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY") for case in (str, str.lower)
]
DEADLINE = 0.6
LATE = 0.6
SMALL = Limits(answer_bytes=1024)


def get(address: Address, *, seconds: float = 5.0, limits: Limits = LIMITS) -> Answer:
    return request(address, "GET", "/api/version", seconds=seconds, limits=limits)


def failure(call: Callable[[], object]) -> ExplanationUnavailable:
    with pytest.raises(ExplanationUnavailable) as caught:
        call()
    return caught.value


def ends_at_the_deadline(address: Address, data: bytes | None = None, **limits: Any) -> None:
    """The request fails as ``timeout``, at the deadline: not before, not much after."""
    method: Literal["GET", "POST"] = "GET" if data is None else "POST"
    start = time.monotonic()
    caught = failure(
        lambda: request(
            address, method, "/api/generate", data, seconds=DEADLINE, limits=Limits(**limits)
        )
    )
    elapsed = time.monotonic() - start
    assert caught.reason is Unavailable.TIMEOUT
    assert DEADLINE * 0.9 <= elapsed <= DEADLINE + LATE


@pytest.fixture
def resolvers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every call to a resolver function, which fails: the list must stay empty."""
    asked: list[str] = []

    def resolver(*args: Any, **kwargs: Any) -> Any:
        asked.append(repr(args))
        raise OSError("no resolver here")

    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
        monkeypatch.setattr(socket, name, resolver)
    return asked


def test_an_answer_is_its_status_and_body() -> None:
    with ScriptedOllama(as_json({"version": "0.6.2"}), body(b"nope", 404)) as ollama:
        assert get(ollama.address) == Answer(200, b'{"version": "0.6.2"}')
        assert get(ollama.address) == Answer(404, b"nope")
    assert ollama.paths() == [("GET", "/api/version")] * 2


# --- no resolver, no proxy, no redirect [0013.10] ------------------------------------------------


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_no_resolver_is_asked(host: str, resolvers: list[str]) -> None:
    # [0013.10] localhost is 127.0.0.1 from the settings on: the socket gets an address.
    with ScriptedOllama() as ollama:
        address = address_from({"SAFECLEAN_OLLAMA_URL": f"http://{host}:{ollama.address.port}"})
        assert get(address).status == 200
    assert resolvers == []
    assert ollama.received[0].header("Host") == f"127.0.0.1:{ollama.address.port}"


def test_ipv6_loopback_without_a_resolver(resolvers: list[str]) -> None:
    # [0013.10]
    with ScriptedOllama(host="::1") as ollama:
        address = address_from({"SAFECLEAN_OLLAMA_URL": f"http://[::1]:{ollama.address.port}"})
        assert get(address).status == 200
    assert resolvers == []
    assert ollama.received[0].header("Host") == f"[::1]:{ollama.address.port}"


def test_proxy_settings_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # [0013.10] Through a proxy the request line would carry the whole URL.
    with ScriptedOllama() as ollama, ScriptedOllama() as proxy:
        for name in PROXY_VARIABLES:
            monkeypatch.setenv(name, proxy.address.url)
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(name, raising=False)
        assert get(ollama.address).status == 200
        request(ollama.address, "POST", "/api/generate", b"{}", seconds=5)
    assert proxy.connections == 0
    assert ollama.paths() == [("GET", "/api/version"), ("POST", "/api/generate")]


def test_proxy_settings_are_ignored_from_the_first_request() -> None:
    # [0013.10] A fresh interpreter: urllib, say, builds its opener from them on first use.
    with ScriptedOllama() as ollama, ScriptedOllama() as proxy:
        env = {k: v for k, v in os.environ.items() if k.lower() != "no_proxy"}
        env |= {name: proxy.address.url for name in PROXY_VARIABLES}
        env["PYTHONPATH"] = str(SRC)
        code = (
            "from safeclean.llm.settings import Address\n"
            "from safeclean.llm.transport import request\n"
            f"address = Address('127.0.0.1', {ollama.address.port})\n"
            "print(request(address, 'GET', '/api/version', seconds=5).status)\n"
        )
        run = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30
        )
    assert (run.stdout, proxy.connections) == ("200\n", 0)
    assert ollama.paths() == [("GET", "/api/version")]


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("elsewhere", ["second", "http://192.0.2.1/api/version"])
def test_a_redirect_is_not_followed(status: int, elsewhere: str) -> None:
    # [0013.10] Not to another loopback server, not beyond: nothing is sent to the Location.
    with ScriptedOllama() as second:
        location = f"{second.address.url}/api/version" if elsewhere == "second" else elsewhere
        with ScriptedOllama(redirect(location, status)) as ollama:
            caught = failure(lambda: get(ollama.address))
    assert caught.reason is Unavailable.REDIRECT
    assert caught.detail == f"{status} to {location!r}, not followed"
    assert (ollama.connections, second.connections) == (1, 0)


def test_nothing_listening_is_unreachable() -> None:
    with socket.create_server(("127.0.0.1", 0)) as taken:
        free = Address("127.0.0.1", taken.getsockname()[1])
    assert failure(lambda: get(free)).reason is Unavailable.UNREACHABLE


def test_closed_without_answering_is_unreachable() -> None:
    with ScriptedOllama(raw(b"")) as ollama:
        assert failure(lambda: get(ollama.address)).reason is Unavailable.UNREACHABLE


def test_what_is_not_http_does_not_answer_as_ollama() -> None:
    with ScriptedOllama(raw(b"SSH-2.0-OpenSSH_9.6\r\n")) as ollama:
        assert failure(lambda: get(ollama.address)).reason is Unavailable.NOT_OLLAMA


# --- one deadline for connecting, sending and reading [0013.12] ----------------------------------


def test_no_time_left_sends_nothing() -> None:
    # [0013.12]
    with ScriptedOllama() as ollama:
        assert failure(lambda: get(ollama.address, seconds=0)).reason is Unavailable.TIMEOUT
    assert ollama.connections == 0


@pytest.mark.skipif(sys.platform != "linux", reason="a full queue makes connect wait on Linux")
def test_connecting_counts_toward_the_deadline() -> None:
    # [0013.12]
    with held_queue() as address:
        ends_at_the_deadline(address)


def test_sending_counts_toward_the_deadline() -> None:
    # [0013.12] 64 MiB to a server that never reads: sending blocks once the buffers are full.
    with never_read() as address:
        ends_at_the_deadline(address, b"x" * (64 << 20), request_bytes=128 << 20)


def test_a_silent_server_ends_at_the_deadline() -> None:
    # [0013.12]
    with ScriptedOllama(silence) as ollama:
        ends_at_the_deadline(ollama.address)


def test_slow_headers_end_at_the_deadline() -> None:
    # [0013.12] A byte every 50 ms: no single read waits long, the whole answer would take 3 s.
    with ScriptedOllama(drip(head(200, length=2) + b"{}", every=0.05)) as ollama:
        ends_at_the_deadline(ollama.address)


def test_a_slow_body_ends_at_the_deadline() -> None:
    # [0013.12]
    with ScriptedOllama(phases(raw(head(200, length=100)), drip(b"x" * 100, 0.05))) as ollama:
        ends_at_the_deadline(ollama.address)


def test_slow_phases_add_up_to_one_deadline() -> None:
    # [0013.12] Headers after 0.35 s, the body 0.35 s later: each within 0.6 s, not both.
    slow = phases(after(0.35, head(200, length=2)), after(0.35, b"{}"))
    with ScriptedOllama(slow) as ollama:
        ends_at_the_deadline(ollama.address)
    with ScriptedOllama(slow) as ollama:
        assert get(ollama.address, seconds=3) == Answer(200, b"{}")


def test_an_answer_within_the_deadline_is_read_whole() -> None:
    # [0013.12]
    with ScriptedOllama(phases(raw(head(200, length=10)), drip(b"0123456789", 0.02))) as ollama:
        assert get(ollama.address, seconds=3) == Answer(200, b"0123456789")


# --- bounded sizes [0013.12] ---------------------------------------------------------------------


@pytest.mark.parametrize("framing", [body, until_closed, chunked])
def test_an_answer_of_exactly_the_limit_is_read(framing: Callable[[bytes], Any]) -> None:
    # [0013.12]
    with ScriptedOllama(framing(b"x" * 1024)) as ollama:
        assert get(ollama.address, limits=SMALL) == Answer(200, b"x" * 1024)


@pytest.mark.parametrize(
    ("framing", "detail"),
    [
        (body, "Content-Length 1025 is over 1024"),
        (until_closed, "the answer is over 1024 bytes"),
        (chunked, "the answer is over 1024 bytes"),
    ],
)
def test_one_byte_over_the_limit_is_too_large(framing: Callable[[bytes], Any], detail: str) -> None:
    # [0013.12]
    with ScriptedOllama(framing(b"x" * 1025)) as ollama:
        caught = failure(lambda: get(ollama.address, limits=SMALL))
    assert (caught.reason, caught.detail) == (Unavailable.TOO_LARGE, detail)


def test_an_endless_answer_stops_at_the_limit_not_the_deadline() -> None:
    # [0013.12]
    with ScriptedOllama(endless()) as ollama:
        start = time.monotonic()
        caught = failure(lambda: get(ollama.address, seconds=10, limits=SMALL))
        elapsed = time.monotonic() - start
    assert caught.reason is Unavailable.TOO_LARGE
    assert elapsed < 2


def test_a_short_content_length_reads_no_more() -> None:
    # [0013.12]
    with ScriptedOllama(raw(head(200, length=10) + b"x" * 100_000)) as ollama:
        assert get(ollama.address) == Answer(200, b"x" * 10)


def test_a_request_body_over_the_limit_is_refused_before_connecting() -> None:
    # [0013.12]
    with ScriptedOllama() as ollama:
        with pytest.raises(ValueError, match="4097 bytes is over 4096"):
            request(ollama.address, "POST", "/api/generate", b"x" * 4097, seconds=5)
        assert ollama.connections == 0
        request(ollama.address, "POST", "/api/generate", b"x" * 4096, seconds=5)
    assert ollama.received[0].body == b"x" * 4096


def test_the_default_limits_are_pinned() -> None:
    # [0013.12]
    assert Limits(3.0, 60.0, 64 * 1024, 4 * 1024) == LIMITS
