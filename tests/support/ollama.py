"""A scripted Ollama: a real HTTP server on loopback that records (decision 0013, item 29).

Each connection reads one request, records it, then plays the next answer of the script (the
last one repeats). An answer writes raw bytes, so a test can be slow, silent, endless, wrong or
redirecting at will. Nothing here asks a resolver: the server binds to an address.

A broken client must fail a test, not hang it: every scripted wait ends after ``GIVE_UP``
seconds, and an endless answer after ``ENDLESS_BYTES``, then the server closes.
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType

from kresorter.llm.settings import Address

GIVE_UP = 5.0
ENDLESS_BYTES = 8 << 20


@dataclass(frozen=True)
class Received:
    method: str
    path: str
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def header(self, name: str) -> str | None:
        found = [value for key, value in self.headers if key.lower() == name.lower()]
        return found[0] if found else None


# An answer gets the connection and a stop event to wait on, so a slow one ends with the server.
Answer = Callable[[socket.socket, threading.Event], None]


def head(status: int, headers: tuple[tuple[str, str], ...] = (), *, length: int | None) -> bytes:
    lines = [f"HTTP/1.1 {status} Scripted", "Connection: close"]
    lines += [f"{key}: {value}" for key, value in headers]
    if length is not None:
        lines.append(f"Content-Length: {length}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


def raw(data: bytes) -> Answer:
    def answer(conn: socket.socket, stop: threading.Event) -> None:
        conn.sendall(data)

    return answer


def body(data: bytes, status: int = 200, headers: tuple[tuple[str, str], ...] = ()) -> Answer:
    return raw(head(status, headers, length=len(data)) + data)


def as_json(value: object, status: int = 200) -> Answer:
    data = json.dumps(value).encode("utf-8")
    return body(data, status, (("Content-Type", "application/json; charset=utf-8"),))


def redirect(location: str, status: int = 302) -> Answer:
    return body(b"", status, (("Location", location),))


def until_closed(data: bytes) -> Answer:
    """A body without ``Content-Length``: it ends when the server closes."""
    return raw(head(200, length=None) + data)


def chunked(data: bytes) -> Answer:
    framed = f"{len(data):x}\r\n".encode("ascii") + data + b"\r\n0\r\n\r\n"
    return raw(head(200, (("Transfer-Encoding", "chunked"),), length=None) + framed)


def endless(chunk: bytes = b"x" * 1024, every: float = 0.01) -> Answer:
    """A body that does not end: only a client that stops reading at its limit is quick."""

    def answer(conn: socket.socket, stop: threading.Event) -> None:
        conn.sendall(head(200, length=None))
        give_up = time.monotonic() + GIVE_UP
        for _ in range(ENDLESS_BYTES // len(chunk)):
            if stop.wait(every) or time.monotonic() > give_up:
                return
            conn.sendall(chunk)

    return answer


def drip(data: bytes, every: float) -> Answer:
    """``data`` one byte at a time, ``every`` seconds apart: no single read waits long."""

    def answer(conn: socket.socket, stop: threading.Event) -> None:
        for index in range(len(data)):
            if stop.wait(every):
                return
            conn.sendall(data[index : index + 1])

    return answer


def after(seconds: float, data: bytes) -> Answer:
    def answer(conn: socket.socket, stop: threading.Event) -> None:
        if not stop.wait(seconds):
            conn.sendall(data)

    return answer


def phases(*steps: Answer) -> Answer:
    def answer(conn: socket.socket, stop: threading.Event) -> None:
        for step in steps:
            step(conn, stop)

    return answer


def silence(conn: socket.socket, stop: threading.Event) -> None:
    stop.wait(GIVE_UP)


def held(gate: threading.Event, then: Answer) -> Answer:
    """``then``, once the test sets ``gate``: the answer comes when the test says."""

    def answer(conn: socket.socket, stop: threading.Event) -> None:
        if gate.wait(GIVE_UP):
            then(conn, stop)

    return answer


def generated(text: str) -> Answer:
    """What ``generate`` answers: ``text``, done."""
    return as_json({"response": text, "done": True})


VERSION = as_json({"version": "0.6.2"})
TAGS = as_json({"models": [{"name": "llama3.2:latest"}]})


class ScriptedOllama:
    def __init__(self, *script: Answer, host: str = "127.0.0.1") -> None:
        self._script = list(script) or [as_json({"version": "0.6.2"})]
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self._listener = socket.create_server((host, 0), family=family)
        self.address = Address(host, self._listener.getsockname()[1])
        self.received: list[Received] = []
        self.connections = 0
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._open: list[socket.socket] = []
        self._lock = threading.Lock()

    def __enter__(self) -> ScriptedOllama:
        self._spawn(self._accept)
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._stop.set()
        for thread in self._threads[:1]:
            thread.join(timeout=5)  # the accept loop: no connection comes after it
        self._listener.close()
        with self._lock:
            for conn in self._open:
                with contextlib.suppress(OSError):  # already closed by its thread
                    conn.shutdown(socket.SHUT_RDWR)  # wakes a thread blocked on it
                conn.close()
        for thread in self._threads[1:]:
            thread.join(timeout=5)

    def _spawn(self, target: Callable[..., None], *args: object) -> None:
        thread = threading.Thread(target=target, args=args, daemon=True)
        self._threads.append(thread)
        thread.start()

    def _accept(self) -> None:
        self._listener.settimeout(0.02)  # a blocked accept() would not see the stop
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            conn.settimeout(None)
            with self._lock:
                answer = self._script[min(self.connections, len(self._script) - 1)]
                self.connections += 1
                self._open.append(conn)
            self._spawn(self._serve, conn, answer)

    def _serve(self, conn: socket.socket, answer: Answer) -> None:
        try:
            received = _read_request(conn)
            if received is not None:
                with self._lock:
                    self.received.append(received)
                answer(conn, self._stop)
        except OSError:
            pass  # the client gave up first: that is what many tests are about
        finally:
            conn.close()

    def paths(self) -> list[tuple[str, str]]:
        return [(r.method, r.path) for r in self.received]


def _read_request(conn: socket.socket) -> Received | None:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(65536)
        if not chunk:
            return None
        data += chunk
    header, _, rest = data.partition(b"\r\n\r\n")
    lines = header.decode("latin-1").split("\r\n")
    method, path, _ = lines[0].split(" ", 2)
    headers = tuple(
        (key.strip(), value.strip())
        for key, _, value in (line.partition(":") for line in lines[1:])
    )
    length = int(dict((k.lower(), v) for k, v in headers).get("content-length", "0"))
    while len(rest) < length:
        chunk = conn.recv(65536)
        if not chunk:
            break
        rest += chunk
    return Received(method, path, headers, rest[:length])


def _close_later(sock: socket.socket) -> threading.Timer:
    timer = threading.Timer(GIVE_UP, sock.close)
    timer.daemon = True
    timer.start()
    return timer


@contextmanager
def held_queue(host: str = "127.0.0.1") -> Iterator[Address]:
    """A port whose queue of connections is full: a new connection waits, unanswered (Linux)."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with listener, held:
        listener.bind((host, 0))
        listener.listen(0)
        held.connect(listener.getsockname())
        timer = _close_later(listener)
        yield Address(host, listener.getsockname()[1])
        timer.cancel()


@contextmanager
def never_read(host: str = "127.0.0.1") -> Iterator[Address]:
    """A port that takes connections and never reads them: a large send blocks."""
    with socket.create_server((host, 0)) as listener:
        timer = _close_later(listener)
        yield Address(host, listener.getsockname()[1])
        timer.cancel()
