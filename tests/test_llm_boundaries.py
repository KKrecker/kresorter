"""What the ``llm`` package may touch: its imports, who imports it, no file (decision 0013).

The guards read the AST of ``src`` (``support.imports``). From safeclean, ``llm`` imports only
the package itself (for its version), its own modules and the results it explains, and only the
command-line modules, ``safeclean.environment`` and the window import ``llm`` [0013.21]
[0014.7]. ``llm`` opens, reads and writes no file [0013.22].
"""

import ast

import pytest

from support.imports import imports, ours, sources

LLM = "safeclean.llm"
UI = "safeclean.ui"
EXPLAINED = frozenset(
    {
        "safeclean.analysis.report",
        "safeclean.analysis.score",
        "safeclean.autostart.models",
        "safeclean.organize.planner",
    }
)
FILE_MODULES = frozenset({"tempfile", "sqlite3", "shelve", "pickle"})
FILE_PREFIXES = ("read_", "write_")  # Path.read_text, Path.write_bytes, ...


def _in_llm(name: str) -> bool:
    return name == LLM or name.startswith(f"{LLM}.")


def llm_may_import(name: str) -> bool:
    return not ours(name) or name == "safeclean" or _in_llm(name) or name in EXPLAINED


def may_import_llm(module: str) -> bool:
    """``llm`` itself, ``safeclean.cli`` or ``safeclean.cli_*``, ``safeclean.environment`` (it
    carries the settings environment and the limits to the commands) and the modules of
    ``safeclean.ui`` (0014 item 7 amends 0013 item 21)."""
    last = module.rsplit(".", 1)[-1]
    command_line = last == "cli" or last.startswith("cli_")
    front = module.count(".") == 1 and (command_line or last == "environment")
    window = module == UI or module.startswith(f"{UI}.")
    return _in_llm(module) or front or window


def _opens(node: ast.Name | ast.Attribute) -> bool:
    """``open``, or ``.open`` / ``.read_*`` / ``.write_*`` on anything."""
    if isinstance(node, ast.Name):
        return node.id == "open"
    return node.attr == "open" or node.attr.startswith(FILE_PREFIXES)


def file_uses(source: str) -> list[int]:
    """Lines where ``source`` names a way to open, read or write a file."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name | ast.Attribute) and _opens(node):
            lines.append(node.lineno)
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
            lines += [node.lineno for name in names if name.split(".")[0] in FILE_MODULES]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in FILE_MODULES:
                lines.append(node.lineno)
            lines += [node.lineno for alias in node.names if alias.name == "open"]
    return lines


# --- the guards on made-up modules ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "module", "resolved"),
    [
        ("from safeclean import __version__", "safeclean.llm.transport", "safeclean"),
        ("from safeclean import text", "safeclean.llm.client", "safeclean.text"),
        ("from safeclean import llm", "safeclean.core.walker", "safeclean.llm"),
        ("from safeclean.llm.explain import explain", "safeclean.cli", "safeclean.llm.explain"),
        ("from . import clean", "safeclean.llm.client", "safeclean.llm.clean"),
        ("from .. import text", "safeclean.llm.client", "safeclean.text"),
        ("from ..core.policy import PathPolicy", "safeclean.llm.client", "safeclean.core.policy"),
        ("from .llm import client", "safeclean.text", "safeclean.llm.client"),
        ("from .settings import Address", "safeclean.llm", "safeclean.llm.settings"),
        ("import safeclean.storage.db", "safeclean.llm.client", "safeclean.storage.db"),
        ("importlib.import_module('safeclean.cli')", "safeclean.llm.client", "safeclean.cli"),
        ("__import__('safeclean.text')", "safeclean.llm.client", "safeclean.text"),
    ],
)
def test_imports_are_resolved(source: str, module: str, resolved: str) -> None:
    # [0013.21]
    is_package = module == LLM
    assert imports(source, module, is_package=is_package) == [(1, resolved)]


@pytest.mark.parametrize(
    ("name", "allowed"),
    [
        ("safeclean", True),
        ("safeclean.llm.subjects", True),
        ("safeclean.analysis.report", True),
        ("safeclean.organize.planner", True),
        ("json", True),
        ("safeclean.text", False),
        ("safeclean.cli", False),
        ("safeclean.analysis.duplicates", False),
        ("safeclean.organize.mover", False),
        ("safeclean.storage.db", False),
        ("safeclean.llmx", False),
    ],
)
def test_what_llm_may_import(name: str, allowed: bool) -> None:
    # [0013.21]
    assert llm_may_import(name) is allowed


@pytest.mark.parametrize(
    ("module", "allowed"),
    [
        ("safeclean.cli", True),
        ("safeclean.cli_analyze", True),
        ("safeclean.llm.explain", True),
        ("safeclean.environment", True),
        ("safeclean.ui", True),
        ("safeclean.ui.findings", True),
        ("safeclean.text", False),
        ("safeclean.core.cli_tools", False),
        ("safeclean.core.environment", False),
        ("safeclean.uix", False),
        ("safeclean.core.ui", False),
        ("safeclean.organize.planner", False),
        ("safeclean.client", False),
    ],
)
def test_who_may_import_llm(module: str, allowed: bool) -> None:
    # [0013.21] [0014.7] the window too
    assert may_import_llm(module) is allowed


@pytest.mark.parametrize(
    "source",
    [
        "open('x')",
        "with open(p, 'rb') as f: pass",
        "read = open",
        "import os\nos.open('x', os.O_RDONLY)",
        "path.open()",
        "path.read_text()",
        "path.read_bytes()",
        "path.write_text('x')",
        "path.write_bytes(b'x')",
        "import tempfile",
        "import sqlite3",
        "import shelve",
        "import pickle",
        "from tempfile import mkstemp",
        "from os import open",
        "from io import open as io_open",
    ],
)
def test_detector_flags_a_file(source: str) -> None:
    # [0013.22]
    assert file_uses(source) != []


def test_detector_allows_the_rest() -> None:
    # [0013.22]
    source = "import json\nanswer.read(10)\nsock.recv_into(buf)\nopened = 1\nreader.reading()"
    assert file_uses(source) == []


# --- the guards on src ---------------------------------------------------------------------------


def test_llm_imports_only_what_it_explains() -> None:
    # [0013.21]
    offenders = [
        f"{module}:{line} {name}"
        for module, path in sources()
        if _in_llm(module)
        for line, name in imports(
            path.read_text(encoding="utf-8"), module, is_package=path.name == "__init__.py"
        )
        if not llm_may_import(name)
    ]
    assert offenders == []


def test_only_the_command_line_imports_llm() -> None:
    # [0013.21]
    offenders = [
        f"{module}:{line} {name}"
        for module, path in sources()
        if not may_import_llm(module)
        for line, name in imports(
            path.read_text(encoding="utf-8"), module, is_package=path.name == "__init__.py"
        )
        if _in_llm(name)
    ]
    assert offenders == []


def test_llm_opens_no_file() -> None:
    # [0013.22]
    offenders = [
        f"{module}:{line}"
        for module, path in sources()
        if _in_llm(module)
        for line in file_uses(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_guards_see_llm_and_its_importers() -> None:
    # [0013.21] The guards read something: the package, and the modules that use it.
    modules = dict(sources())
    assert {name for name in modules if _in_llm(name)} >= {LLM, f"{LLM}.explain"}
    importers = {
        module
        for module, path in modules.items()
        if not _in_llm(module)
        and any(_in_llm(name) for _, name in imports(path.read_text(encoding="utf-8"), module))
    }
    assert importers == {
        "safeclean.cli_analyze",
        "safeclean.cli_autostart",
        "safeclean.cli_llm",
        "safeclean.environment",
    }
