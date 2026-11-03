"""What the ``llm`` package may touch: its imports, who imports it, no file (decision 0013).

The guards read the AST of ``src`` (``support.imports``). From kresorter, ``llm`` imports only
the package itself (for its version), its own modules and the results it explains, and only the
command-line modules, ``kresorter.environment`` and the window import ``llm`` [0013.21]
[0014.7]. ``llm`` opens, reads and writes no file [0013.22].
"""

import pytest

from support.imports import file_uses, imports, ours, sources

LLM = "kresorter.llm"
UI = "kresorter.ui"
EXPLAINED = frozenset(
    {
        "kresorter.analysis.report",
        "kresorter.analysis.score",
        "kresorter.autostart.models",
        "kresorter.organize.planner",
    }
)


def _in_llm(name: str) -> bool:
    return name == LLM or name.startswith(f"{LLM}.")


def llm_may_import(name: str) -> bool:
    return not ours(name) or name == "kresorter" or _in_llm(name) or name in EXPLAINED


def may_import_llm(module: str) -> bool:
    """``llm`` itself, ``kresorter.cli`` or ``kresorter.cli_*``, ``kresorter.environment`` (it
    carries the settings environment and the limits to the commands) and the modules of
    ``kresorter.ui`` (0014 item 7 amends 0013 item 21)."""
    last = module.rsplit(".", 1)[-1]
    command_line = last == "cli" or last.startswith("cli_")
    front = module.count(".") == 1 and (command_line or last == "environment")
    window = module == UI or module.startswith(f"{UI}.")
    return _in_llm(module) or front or window


# --- the guards on made-up modules ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "module", "resolved"),
    [
        ("from kresorter import __version__", "kresorter.llm.transport", "kresorter"),
        ("from kresorter import text", "kresorter.llm.client", "kresorter.text"),
        ("from kresorter import llm", "kresorter.core.walker", "kresorter.llm"),
        ("from kresorter.llm.explain import explain", "kresorter.cli", "kresorter.llm.explain"),
        ("from . import clean", "kresorter.llm.client", "kresorter.llm.clean"),
        ("from .. import text", "kresorter.llm.client", "kresorter.text"),
        ("from ..core.policy import PathPolicy", "kresorter.llm.client", "kresorter.core.policy"),
        ("from .llm import client", "kresorter.text", "kresorter.llm.client"),
        ("from .settings import Address", "kresorter.llm", "kresorter.llm.settings"),
        ("import kresorter.storage.db", "kresorter.llm.client", "kresorter.storage.db"),
        ("importlib.import_module('kresorter.cli')", "kresorter.llm.client", "kresorter.cli"),
        ("__import__('kresorter.text')", "kresorter.llm.client", "kresorter.text"),
    ],
)
def test_imports_are_resolved(source: str, module: str, resolved: str) -> None:
    # [0013.21]
    is_package = module == LLM
    assert imports(source, module, is_package=is_package) == [(1, resolved)]


@pytest.mark.parametrize(
    ("name", "allowed"),
    [
        ("kresorter", True),
        ("kresorter.llm.subjects", True),
        ("kresorter.analysis.report", True),
        ("kresorter.organize.planner", True),
        ("json", True),
        ("kresorter.text", False),
        ("kresorter.cli", False),
        ("kresorter.analysis.duplicates", False),
        ("kresorter.organize.mover", False),
        ("kresorter.storage.db", False),
        ("kresorter.llmx", False),
    ],
)
def test_what_llm_may_import(name: str, allowed: bool) -> None:
    # [0013.21]
    assert llm_may_import(name) is allowed


@pytest.mark.parametrize(
    ("module", "allowed"),
    [
        ("kresorter.cli", True),
        ("kresorter.cli_analyze", True),
        ("kresorter.llm.explain", True),
        ("kresorter.environment", True),
        ("kresorter.ui", True),
        ("kresorter.ui.findings", True),
        ("kresorter.text", False),
        ("kresorter.core.cli_tools", False),
        ("kresorter.core.environment", False),
        ("kresorter.uix", False),
        ("kresorter.core.ui", False),
        ("kresorter.organize.planner", False),
        ("kresorter.client", False),
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
    # [0013.21] The guards read something: the package, and the modules that use it outside the
    # window (the window's modules may, 0014 item 7, and which of them do grows with it).
    modules = dict(sources())
    assert {name for name in modules if _in_llm(name)} >= {LLM, f"{LLM}.explain"}
    importers = {
        module
        for module, path in modules.items()
        if not _in_llm(module)
        and not (module == UI or module.startswith(f"{UI}."))
        and any(_in_llm(name) for _, name in imports(path.read_text(encoding="utf-8"), module))
    }
    assert importers == {
        "kresorter.cli_analyze",
        "kresorter.cli_autostart",
        "kresorter.cli_llm",
        "kresorter.environment",
    }
