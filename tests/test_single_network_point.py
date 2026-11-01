"""Only a module on the allowlist may open a connection (decision 0013).

The guard reads the AST of ``src`` [0013.7]: a networking module of the standard library,
imported statically or by a literal name given to ``__import__`` / ``importlib.import_module``,
may be imported only by a module on the allowlist, and only as the allowlist says. Like the
deletion point (0001, item 1), the allowlist grows only with a decision, and what it allows
must be what the module really imports.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

NETWORK_MODULES = frozenset(
    {
        "_socket",
        "_ssl",
        "asyncio",
        "ftplib",
        "http",
        "imaplib",
        "poplib",
        "selectors",
        "smtplib",
        "socket",
        "socketserver",
        "ssl",
        "urllib",
        "webbrowser",
        "xmlrpc",
    }
)
# Step 3 of the step 6 plan makes it {"src/safeclean/llm/transport.py": http.client, socket}.
ALLOWED: dict[str, frozenset[str]] = {}


def _network(name: str) -> bool:
    return name.split(".")[0] in NETWORK_MODULES


def _dynamic_import(node: ast.Call) -> str | None:
    """The literal module name of ``__import__("x")`` or ``import_module("x")``, if any."""
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if name in ("__import__", "import_module") and node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    return None


def network_imports(source: str) -> list[tuple[int, str]]:
    """Each networking import in ``source``: its line and the module, as it is named."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names if _network(alias.name)]
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            if node.module in NETWORK_MODULES:  # ``from http import client`` is http.client
                found += [(node.lineno, f"{node.module}.{alias.name}") for alias in node.names]
            elif _network(node.module):
                found.append((node.lineno, node.module))
        elif isinstance(node, ast.Call):
            name = _dynamic_import(node)
            if name is not None and _network(name):
                found.append((node.lineno, name))
    return found


@pytest.mark.parametrize(
    ("snippet", "module"),
    [
        ("import socket", "socket"),
        ("import _socket", "_socket"),
        ("import http.client", "http.client"),
        ("from http import client", "http.client"),
        ("from http.client import HTTPConnection", "http.client"),
        ("import urllib.request as request", "urllib.request"),
        ("from urllib import request", "urllib.request"),
        ("from urllib.parse import urlsplit", "urllib.parse"),
        ("import ssl, json", "ssl"),
        ("import asyncio", "asyncio"),
        ("import xmlrpc.client", "xmlrpc.client"),
        ("import webbrowser", "webbrowser"),
        ("socket = __import__('socket')", "socket"),
        ("import importlib\nnet = importlib.import_module('http.client')", "http.client"),
        ("from importlib import import_module\nnet = import_module('ssl')", "ssl"),
    ],
)
def test_detector_names_each_network_import(snippet: str, module: str) -> None:
    assert [name for _, name in network_imports(snippet)] == [module]


def test_detector_allows_other_imports() -> None:
    source = (
        "import json\nimport sockets_notes\nfrom . import http\nfrom .socket import x\n"
        "from importlib.resources import files\nimport_module(name)\n"
    )
    assert network_imports(source) == []


def test_only_the_allowlist_imports_the_network() -> None:
    offenders = [
        f"{relative}:{line}: {module}"
        for path in sorted(SRC.rglob("*.py"))
        for relative in [path.relative_to(ROOT).as_posix()]
        for line, module in network_imports(path.read_text(encoding="utf-8"))
        if module not in ALLOWED.get(relative, frozenset())
    ]
    assert offenders == []


def test_the_allowlist_is_pinned() -> None:
    # Empty until step 3 of the step 6 plan. Growing it needs a decision, not a quiet edit.
    assert ALLOWED == {}


def test_what_is_allowed_is_really_imported() -> None:
    # A stale entry would be a silent hole: each allowed import must be there.
    for relative, modules in ALLOWED.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert {name for _, name in network_imports(source)} == modules
