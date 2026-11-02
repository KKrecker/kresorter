"""What may import Qt, and what the window may import (decision 0014).

No module outside ``safeclean.ui`` imports PySide6 or shiboken6, the package depends on nothing,
and the CLI runs every command with Qt made unimportable [0014.1]. From PySide6 the window
imports only QtCore, QtGui and QtWidgets, never names ``QProcess`` or ``QDesktopServices``, and
imports no module of the CLI [0014.7]. Only ``safeclean.ui.settings`` opens, reads or writes a
file, and no module of the window names Qt's own ways to store [0014.35]. The guards read the
AST of ``src`` (``support.imports``).
"""

import argparse
import ast
import importlib
import io
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

from safeclean import cli
from safeclean.environment import Environment
from support.cli import autostart_context, scan_context
from support.imports import SRC, file_uses, imports, sources

UI = "safeclean.ui"
QT_ROOTS = frozenset({"PySide6", "shiboken6"})
QT_ALLOWED = frozenset({"PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"})
QT_FORBIDDEN_NAMES = frozenset({"QProcess", "QDesktopServices"})
QT_STORAGE_NAMES = frozenset({"QSettings", "QFile", "QSaveFile", "QTemporaryFile"})
SETTINGS = "safeclean.ui.settings"  # the one module of the window that touches a file
REFUSED_URL = {"SAFECLEAN_OLLAMA_URL": "http://192.0.2.1:11434"}  # not loopback: no connection


def in_ui(module: str) -> bool:
    return module == UI or module.startswith(f"{UI}.")


def _dynamic(node: ast.Call) -> str | None:
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if name in ("__import__", "import_module") and node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    return None


def qt_imports(source: str) -> list[tuple[int, str]]:
    """Each Qt module ``source`` imports, with its line: ``from PySide6 import QtCore`` is
    ``PySide6.QtCore``, ``from PySide6.QtCore import Qt`` is ``PySide6.QtCore``."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            if node.module in QT_ROOTS:
                found += [(node.lineno, f"{node.module}.{alias.name}") for alias in node.names]
            else:
                found.append((node.lineno, node.module))
        elif isinstance(node, ast.Call) and (name := _dynamic(node)) is not None:
            found.append((node.lineno, name))
    return [(line, name) for line, name in found if name.split(".")[0] in QT_ROOTS]


def qt_allowed(name: str) -> bool:
    """A shiboken6 module, or one of the three PySide6 modules (or a name inside them)."""
    return name.split(".")[0] == "shiboken6" or ".".join(name.split(".")[:2]) in QT_ALLOWED


def forbidden_names(
    source: str, names: frozenset[str] = QT_FORBIDDEN_NAMES
) -> list[tuple[int, str]]:
    """Where ``source`` names one of ``names`` (by default ``QProcess`` or
    ``QDesktopServices``), however it reaches them."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            found.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute):
            found.append((node.lineno, node.attr))
        elif isinstance(node, ast.ImportFrom):
            found += [(node.lineno, alias.name) for alias in node.names]
    return [(line, name) for line, name in found if name in names]


def is_cli(name: str) -> bool:
    last = name.rsplit(".", 1)[-1]
    return (
        name.count(".") == 1
        and name.startswith("safeclean.")
        and (last == "cli" or last.startswith("cli_"))
    )


def ui_sources() -> Iterator[tuple[str, Path]]:
    return ((module, path) for module, path in sources() if in_ui(module))


# --- the guards on made-up modules ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "found"),
    [
        ("import PySide6", ["PySide6"]),
        ("import PySide6.QtNetwork", ["PySide6.QtNetwork"]),
        ("from PySide6 import QtCore, QtNetwork", ["PySide6.QtCore", "PySide6.QtNetwork"]),
        ("from PySide6.QtWidgets import QWidget", ["PySide6.QtWidgets"]),
        ("import shiboken6", ["shiboken6"]),
        ("importlib.import_module('PySide6.QtWebEngineCore')", ["PySide6.QtWebEngineCore"]),
        ("__import__('PySide6')", ["PySide6"]),
        ("import json\nfrom pathlib import Path\nfrom . import tasks", []),
    ],
)
def test_qt_imports_are_found(source: str, found: list[str]) -> None:
    # [0014.1] [0014.7]
    assert [name for _, name in qt_imports(source)] == found


@pytest.mark.parametrize(
    ("name", "allowed"),
    [
        ("PySide6.QtCore", True),
        ("PySide6.QtGui", True),
        ("PySide6.QtWidgets", True),
        ("shiboken6", True),
        ("PySide6", False),
        ("PySide6.QtNetwork", False),
        ("PySide6.QtWebEngineWidgets", False),
        ("PySide6.QtQml", False),
        ("PySide6.QtCoreX", False),
    ],
)
def test_what_the_window_may_import_from_qt(name: str, allowed: bool) -> None:
    # [0014.7]
    assert qt_allowed(name) is allowed


@pytest.mark.parametrize(
    ("source", "lines"),
    [
        ("from PySide6.QtCore import QProcess", [1]),
        ("from PySide6 import QtCore\nQtCore.QProcess()", [2]),
        ("from PySide6.QtGui import QDesktopServices", [1]),
        ("QDesktopServices.openUrl(url)", [1]),
        ("from PySide6.QtCore import QThread, QTimer\nQProcessing = 1", []),
    ],
)
def test_qprocess_and_qdesktopservices_are_found(source: str, lines: list[int]) -> None:
    # [0014.7]
    assert [line for line, _ in forbidden_names(source)] == lines


def test_qt_s_ways_to_store_are_found() -> None:
    # [0014.35]
    source = "from PySide6.QtCore import QSettings\nQtCore.QSaveFile(name)\nQFile\nQProcess\n"
    assert sorted(forbidden_names(source, QT_STORAGE_NAMES)) == [
        (1, "QSettings"),
        (2, "QSaveFile"),
        (3, "QFile"),
    ]


@pytest.mark.parametrize(
    ("name", "cli_module"),
    [
        ("safeclean.cli", True),
        ("safeclean.cli_quarantine", True),
        ("safeclean.environment", False),
        ("safeclean.client", False),
        ("safeclean.core.cli_tools", False),
        ("safeclean.ui.cli", False),
    ],
)
def test_a_cli_module_is_recognized(name: str, cli_module: bool) -> None:
    # [0014.7]
    assert is_cli(name) is cli_module


# --- the guards on src ---------------------------------------------------------------------------


def test_no_module_outside_the_window_imports_qt() -> None:
    # [0014.1]
    offenders = [
        f"{module}:{line} {name}"
        for module, path in sources()
        if not in_ui(module)
        for line, name in qt_imports(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_guards_read_every_module() -> None:
    # [0014.1] [0014.7] the guards see the whole package, the CLI and the environment included
    modules = {module for module, _ in sources()}
    assert {"safeclean", "safeclean.cli", "safeclean.environment", "safeclean.llm"} <= modules
    assert len(modules) == len(list((SRC / "safeclean").rglob("*.py")))


def test_the_window_imports_from_qt_only_what_it_may() -> None:
    # [0014.7]
    offenders = [
        f"{module}:{line} {name}"
        for module, path in ui_sources()
        for line, name in qt_imports(path.read_text(encoding="utf-8"))
        if not qt_allowed(name)
    ]
    assert offenders == []


def test_the_window_names_no_qprocess_and_no_qdesktopservices() -> None:
    # [0014.7]
    offenders = [
        f"{module}:{line} {name}"
        for module, path in ui_sources()
        for line, name in forbidden_names(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_window_stores_nothing_but_its_settings() -> None:
    # [0014.35] No finding, path, plan or explanation is stored: only the settings module
    # touches a file, and nothing in the window uses Qt's settings or files.
    modules = dict(ui_sources())
    assert SETTINGS in modules
    files = [
        f"{module}:{line}"
        for module, path in modules.items()
        if module != SETTINGS
        for line in file_uses(path.read_text(encoding="utf-8"))
    ]
    stores = [
        f"{module}:{line} {name}"
        for module, path in modules.items()
        for line, name in forbidden_names(path.read_text(encoding="utf-8"), QT_STORAGE_NAMES)
    ]
    assert files == []
    assert stores == []


def test_the_window_imports_no_module_of_the_cli() -> None:
    # [0014.7]
    offenders = [
        f"{module}:{line} {name}"
        for module, path in ui_sources()
        for line, name in imports(
            path.read_text(encoding="utf-8"), module, is_package=path.name == "__init__.py"
        )
        if is_cli(name)
    ]
    assert offenders == []


# --- no dependency, and the CLI without Qt -------------------------------------------------------


def test_the_package_depends_on_nothing() -> None:
    # [0014.1]
    project = tomllib.loads((SRC.parent / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == []


@pytest.mark.usefixtures("without_qt")
@pytest.mark.parametrize("name", ["PySide6", "PySide6.QtWidgets", "shiboken6"])
def test_without_qt_nothing_of_it_imports(name: str) -> None:
    # [0014.1] the fixture the next test relies on
    with pytest.raises(ImportError):
        importlib.import_module(name)


COMMANDS = {
    "scan": (["scan"], 0),
    "analyze": (["analyze"], 0),
    "quarantine": (["quarantine", "list"], 0),
    "organize": (["organize", "list"], 0),
    "autostart": (["autostart", "list"], 0),
    "recover": (["recover"], 0),
    "llm": (["llm", "status"], 1),
}


def test_every_command_is_run_without_qt() -> None:
    # [0014.1]
    parser = cli.build_parser()
    (commands,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert set(commands.choices) == set(COMMANDS)


@pytest.mark.usefixtures("without_qt")
@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_the_cli_runs_without_qt(command: str, tmp_path: Path) -> None:
    # [0014.1]
    zone = tmp_path / "zone"
    zone.mkdir()
    args, expected = COMMANDS[command]
    environment = Environment(
        scan_context=lambda: scan_context(tmp_path, zone, tmp_path / "data"),
        autostart_context=lambda: autostart_context("linux", tmp_path),
        llm_env=REFUSED_URL,
    )
    out, err = io.StringIO(), io.StringIO()
    assert cli.main(args, out=out, err=err, environment=environment) == expected, err.getvalue()
