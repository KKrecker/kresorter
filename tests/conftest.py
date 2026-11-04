"""Fixtures shared by several test files (decision 0011, item 123).

pytest finds a fixture by its name, so these are not imported; helpers are imported by name
from ``support``, and boundary fakes from ``fakes``. One fixture is used by every test: no
test reaches beyond loopback or asks a resolver (decision 0013, item 29). Qt, for the window's
tests, runs offscreen, and they reach no live system (decision 0014, items 38 and 39).
"""

import ipaddress
import os
import socket
import sys
from collections.abc import Callable, Sequence
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from kresorter.core.scanner import ScanContext
from support.annotations import commands, failures, uncovered
from support.artifacts import Built, Installed, built_for_the_run, install, lend_qt
from support.cli import scan_context
from support.kernel import FakeCtypes
from support.live import guard
from support.offscreen import system_fonts

# The window's tests run on Qt's offscreen platform, set before any application is made
# (decision 0014, item 38), with the system's fonts on Windows too.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
system_fonts()

_IPV4_LOOPBACK = ipaddress.IPv4Network("127.0.0.0/8")
_IPV6_LOOPBACK = ipaddress.IPv6Address("::1")
_RESOLVERS = ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr")
_QT_ROOTS = ("PySide6", "shiboken6")
_WINDOW_TESTS = Path(__file__).resolve().parent / "ui"


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


@pytest.fixture(autouse=True)
def no_live_system(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """A test of the window (``tests/ui``) reaches no live system: the running system's
    contexts are refused, home is temporary, the local AI's address is refused (0014 item 39,
    ``support.live``)."""
    if _WINDOW_TESTS in Path(request.node.path).resolve().parents:
        guard(monkeypatch, tmp_path_factory.mktemp("home"))


@pytest.fixture(scope="session")
def built(tmp_path_factory: pytest.TempPathFactory) -> Built:
    """The sdist, and the wheel built from it: once per run, offline, or those of CI's build job
    (decision 0015, item 21)."""
    return built_for_the_run(tmp_path_factory.mktemp("built"))


@pytest.fixture(scope="session")
def installed(built: Built, tmp_path_factory: pytest.TempPathFactory) -> Installed:
    """That wheel in a new virtual environment, offline: once per run (decision 0015)."""
    return install(built.wheel, tmp_path_factory.mktemp("installed"))


@pytest.fixture(scope="session")
def installed_with_qt(built: Built, tmp_path_factory: pytest.TempPathFactory) -> Installed:
    """The wheel in another environment, with the running one's PySide6 lent to it (decision
    0015, item 17): once per run."""
    installed = install(built.wheel, tmp_path_factory.mktemp("installed-with-qt"))
    lend_qt(installed.venv)
    return installed


@pytest.fixture
def kernel32(monkeypatch: pytest.MonkeyPatch) -> FakeCtypes:
    """``ctypes`` made a fake for the test, so that ``Kernel32`` loads on any system: its
    ``CreateFileW`` answers a handle, its ``CloseHandle`` succeeds (decision 0016, item 6)."""
    module = FakeCtypes()
    monkeypatch.setitem(sys.modules, "ctypes", module)
    return module


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """kresorter's data directory, not made: commands make it, after checking where it is."""
    return tmp_path / "data" / "kresorter"


@pytest.fixture
def zone(tmp_path: Path) -> Path:
    """The one default scan zone, made empty."""
    path = tmp_path / "zone"
    path.mkdir()
    return path


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The home folder: tmp_path, so that the zone is ``~/zone``."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


@pytest.fixture
def scan(tmp_path: Path, zone: Path, data_dir: Path) -> ScanContext:
    """The scan context of a CLI test: ``zone`` and ``data_dir``, a reliable open-file check."""
    return scan_context(tmp_path, zone, data_dir)


@pytest.fixture
def without_qt(monkeypatch: pytest.MonkeyPatch) -> None:
    """PySide6 and shiboken6, and every module under them, cannot be imported, nor any module
    of the window but ``kresorter.ui`` and its launch: imported again, they need Qt (decision
    0014, items 1 and 9)."""
    for name in [name for name in sys.modules if name.split(".")[0] in _QT_ROOTS]:
        monkeypatch.setitem(sys.modules, name, None)
    for root in _QT_ROOTS:
        monkeypatch.setitem(sys.modules, root, None)
    _forget_the_window(monkeypatch)


QT_LIBRARY = "libGL.so.1: cannot open shared object file: No such file or directory"


class _QtWithoutItsLibrary(MetaPathFinder):
    """Every module under PySide6 and shiboken6 fails to load a library, as on a Linux without
    libGL: the error names the module alone (``QtWidgets``), not PySide6."""

    def find_spec(
        self, fullname: str, path: Sequence[str] | None, target: ModuleType | None = None
    ) -> ModuleSpec | None:
        root, _, module = fullname.partition(".")
        if root in _QT_ROOTS and module:
            raise ImportError(QT_LIBRARY, name=module, path=f"/{root}/{module}.abi3.so")
        return None


@pytest.fixture
def qt_without_its_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """PySide6 and shiboken6 are installed, but none of their modules can load a library it
    needs; the window's modules need them again, as without Qt (decision 0014, item 9)."""
    for name in [name for name in sys.modules if name.split(".")[0] in _QT_ROOTS]:
        if "." in name:
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [_QtWithoutItsLibrary(), *sys.meta_path])
    _forget_the_window(monkeypatch)


def _forget_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every module of the window but ``kresorter.ui`` and its launch is imported again."""
    window = sys.modules.get("kresorter.ui")
    for name in [name for name in sys.modules if name.startswith("kresorter.ui.")]:
        if name != "kresorter.ui.launch":
            monkeypatch.delitem(sys.modules, name)
            monkeypatch.delattr(window, name.rsplit(".", 1)[-1], raising=False)


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """On GitHub's runners, the failures as annotations of the job (``support.annotations``)."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    found = failures(terminalreporter.stats, str(terminalreporter.config.rootpath))
    cov = terminalreporter.config.pluginmanager.getplugin("_cov")  # pytest-cov's, its report
    report = getattr(cov, "cov_report", None)
    short = uncovered(report.getvalue()) if report is not None else []
    for line in commands(found, short):
        terminalreporter.write_line(line)
