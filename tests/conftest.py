"""Fixtures shared by several test files (decision 0011, item 123).

pytest finds a fixture by its name, so these are not imported; helpers are imported by name
from ``support``, and boundary fakes from ``fakes``. One fixture is used by every test: no
test reaches beyond loopback or asks a resolver (decision 0013, item 29). Qt, for the window's
tests, runs offscreen.
"""

import ipaddress
import os
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from safeclean.core.scanner import ScanContext
from support.cli import scan_context

# The window's tests run on Qt's offscreen platform, set before any application is made
# (decision 0014, item 38).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_IPV4_LOOPBACK = ipaddress.IPv4Network("127.0.0.0/8")
_IPV6_LOOPBACK = ipaddress.IPv6Address("::1")
_RESOLVERS = ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr")
_QT_ROOTS = ("PySide6", "shiboken6")


def _address(host: object) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.decode() if isinstance(host, bytes) else str(host))
    except (ValueError, UnicodeDecodeError):
        return None


def _on_loopback(sock: socket.socket, address: Any) -> bool:
    """True when ``address`` is not an Internet one, or is loopback written as an address."""
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return True  # AF_UNIX and friends stay on this machine
    host = _address(address[0])
    if isinstance(host, ipaddress.IPv4Address):
        return host in _IPV4_LOOPBACK
    return host == _IPV6_LOOPBACK  # a name is None: tests connect to addresses


def _guard_connect(connect: Callable[[socket.socket, Any], Any]) -> Callable[..., Any]:
    def guarded(sock: socket.socket, address: Any) -> Any:
        if not _on_loopback(sock, address):
            raise AssertionError(f"a test connected beyond loopback: {address!r}")
        return connect(sock, address)

    return guarded


def _guard_sendto(sendto: Callable[..., int]) -> Callable[..., int]:
    def guarded(sock: socket.socket, data: bytes, *rest: Any) -> int:
        if not _on_loopback(sock, rest[-1]):
            raise AssertionError(f"a test sent beyond loopback: {rest[-1]!r}")
        return sendto(sock, data, *rest)

    return guarded


def _guard_resolver(name: str, resolve: Callable[..., Any]) -> Callable[..., Any]:
    def guarded(host: Any, *rest: Any, **options: Any) -> Any:
        if name == "gethostbyaddr" or (host is not None and _address(host) is None):
            raise AssertionError(f"a test asked a resolver: {name}({host!r})")
        return resolve(host, *rest, **options)

    return guarded


@pytest.fixture(autouse=True)
def loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test: nothing connects or sends beyond loopback, no name is resolved, before
    anything leaves (decision 0013, item 29)."""
    monkeypatch.setattr(socket.socket, "connect", _guard_connect(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", _guard_connect(socket.socket.connect_ex))
    monkeypatch.setattr(socket.socket, "sendto", _guard_sendto(socket.socket.sendto))
    for name in _RESOLVERS:
        monkeypatch.setattr(socket, name, _guard_resolver(name, getattr(socket, name)))


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """safeclean's data directory, not made: commands make it, after checking where it is."""
    return tmp_path / "data" / "safeclean"


@pytest.fixture
def zone(tmp_path: Path) -> Path:
    """The one default scan zone, made empty."""
    path = tmp_path / "zone"
    path.mkdir()
    return path


@pytest.fixture
def scan(tmp_path: Path, zone: Path, data_dir: Path) -> ScanContext:
    """The scan context of a CLI test: ``zone`` and ``data_dir``, a reliable open-file check."""
    return scan_context(tmp_path, zone, data_dir)


@pytest.fixture
def without_qt(monkeypatch: pytest.MonkeyPatch) -> None:
    """PySide6 and shiboken6, and every module under them, cannot be imported, nor any module
    of the window but ``safeclean.ui`` and its launch: imported again, they need Qt (decision
    0014, items 1 and 9)."""
    for name in [name for name in sys.modules if name.split(".")[0] in _QT_ROOTS]:
        monkeypatch.setitem(sys.modules, name, None)
    for root in _QT_ROOTS:
        monkeypatch.setitem(sys.modules, root, None)
    window = sys.modules.get("safeclean.ui")
    for name in [name for name in sys.modules if name.startswith("safeclean.ui.")]:
        if name != "safeclean.ui.launch":
            monkeypatch.delitem(sys.modules, name)
            monkeypatch.delattr(window, name.rsplit(".", 1)[-1], raising=False)
