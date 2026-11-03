"""The one network point of kresorter: HTTP to Ollama on loopback (decision 0013, items 7, 10).

``http.client`` without ``urllib``: no proxy setting is read and no redirect is followed. The
socket is made from the address itself, so no resolver is asked. One deadline covers
connecting, sending and every read: before each, the socket waits at most what remains
(item 12).
"""

from __future__ import annotations

import http.client
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from kresorter import __version__
from kresorter.llm.failure import ExplanationUnavailable, Unavailable
from kresorter.llm.settings import Address

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer, WriteableBuffer

Clock = Callable[[], float]


@dataclass(frozen=True)
class Limits:
    check_seconds: float = 3.0
    generate_seconds: float = 60.0
    answer_bytes: int = 64 * 1024
    request_bytes: int = 4 * 1024


LIMITS = Limits()


@dataclass(frozen=True)
class Answer:
    status: int
    body: bytes


class _DeadlineSocket(socket.socket):
    """A socket that never waits past one deadline, whatever it waits for."""

    def __init__(self, family: socket.AddressFamily, deadline: float, clock: Clock) -> None:
        super().__init__(family, socket.SOCK_STREAM)
        self._deadline = deadline
        self._clock = clock

    def wait_at_most_what_remains(self) -> None:
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise TimeoutError("the deadline has passed")
        self.settimeout(remaining)

    def sendall(self, data: ReadableBuffer, flags: int = 0, /) -> None:
        self.wait_at_most_what_remains()
        super().sendall(data, flags)

    def recv_into(self, buffer: WriteableBuffer, nbytes: int = 0, flags: int = 0, /) -> int:
        self.wait_at_most_what_remains()
        return super().recv_into(buffer, nbytes, flags)


class _Connection(http.client.HTTPConnection):
    def __init__(self, address: Address, deadline: float, clock: Clock) -> None:
        super().__init__(address.host, address.port)
        self._family = socket.AF_INET6 if address.ipv6 else socket.AF_INET
        self._deadline = deadline
        self._clock = clock

    def connect(self) -> None:
        """The address as it is: not ``socket.create_connection``, which asks a resolver."""
        sock = _DeadlineSocket(self._family, self._deadline, self._clock)
        try:
            sock.wait_at_most_what_remains()
            sock.connect((self.host, self.port))
        except BaseException:
            sock.close()
            raise
        self.sock = sock


def request(
    address: Address,
    method: Literal["GET", "POST"],
    path: str,
    body: bytes | None = None,
    *,
    seconds: float,
    limits: Limits = LIMITS,
    clock: Clock = time.monotonic,
) -> Answer:
    """One request, one answer of at most ``limits.answer_bytes``, all within ``seconds``."""
    if body is not None and len(body) > limits.request_bytes:
        raise ValueError(f"a request body of {len(body)} bytes is over {limits.request_bytes}")
    deadline = clock() + seconds
    connection = _Connection(address, deadline, clock)
    headers = {
        "User-Agent": f"kresorter/{__version__}",
        "Accept": "application/json",
        "Connection": "close",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        connection.request(method, path, body=body, headers=headers)
        with connection.getresponse() as response:  # its socket closed on every way out
            return _read(response, limits)
    except (OSError, http.client.HTTPException) as error:
        raise _failure(error, deadline, clock) from error
    finally:
        connection.close()


def _read(response: http.client.HTTPResponse, limits: Limits) -> Answer:
    if 300 <= response.status < 400:
        location = response.getheader("Location", "")
        raise ExplanationUnavailable(
            Unavailable.REDIRECT, f"{response.status} to {location!r}, not followed"
        )
    if response.length is not None and response.length > limits.answer_bytes:
        raise ExplanationUnavailable(
            Unavailable.TOO_LARGE, f"Content-Length {response.length} is over {limits.answer_bytes}"
        )
    body = response.read(limits.answer_bytes + 1)
    if len(body) > limits.answer_bytes:
        raise ExplanationUnavailable(
            Unavailable.TOO_LARGE, f"the answer is over {limits.answer_bytes} bytes"
        )
    return Answer(response.status, body)


def _failure(error: Exception, deadline: float, clock: Clock) -> ExplanationUnavailable:
    if isinstance(error, TimeoutError) or clock() >= deadline:
        return ExplanationUnavailable(Unavailable.TIMEOUT, "no whole answer before the deadline")
    if isinstance(error, http.client.HTTPException) and not isinstance(error, ConnectionError):
        return ExplanationUnavailable(Unavailable.NOT_OLLAMA, f"not an HTTP answer ({error!r})")
    return ExplanationUnavailable(Unavailable.UNREACHABLE, str(error) or type(error).__name__)
