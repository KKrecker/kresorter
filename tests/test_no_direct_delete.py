"""Safety guard: no direct file deletion anywhere in project code (see decision 0001).

Complements ruff's banned-api, which cannot see method calls such as ``Path.unlink()``.
The single exception is ``quarantine/purge.py`` (decision 0004, item 8); the allowlist is pinned.
"""

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCANNED_DIRS = ("src", "tests", "scripts", "packaging")

# Method names that delete regardless of the receiver.
FORBIDDEN_METHODS = frozenset({"unlink", "rmdir", "rmtree", "removedirs"})
# Names forbidden only on these modules (``list.remove`` is fine).
FORBIDDEN_MODULE_ATTRS = {"os": frozenset({"remove", "unlink", "rmdir", "removedirs"})}
# The only file allowed to delete: final purge of verified vault copies.
# ``from os import remove`` and friends hide the module from the attribute check.
FORBIDDEN_FROM_IMPORTS = {**FORBIDDEN_MODULE_ATTRS, "shutil": frozenset({"rmtree"})}
ALLOWED_TO_DELETE = frozenset({"src/kresorter/quarantine/purge.py"})


def find_direct_deletes(source: str) -> list[int]:
    """Return line numbers of direct deletion calls or references in ``source``."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute):
            receiver = node.value
            module_attrs = (
                FORBIDDEN_MODULE_ATTRS.get(receiver.id, frozenset())
                if isinstance(receiver, ast.Name)
                else frozenset()
            )
            if node.attr in FORBIDDEN_METHODS or node.attr in module_attrs:
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_FROM_IMPORTS:
            names = FORBIDDEN_FROM_IMPORTS[node.module]
            lines.extend(node.lineno for alias in node.names if alias.name in names)
    return lines


@pytest.mark.parametrize(
    "snippet",
    [
        "import os\nos.remove('x')",
        "import os\nos.unlink('x')",
        "import shutil\nshutil.rmtree('x')",
        "from pathlib import Path\nPath('x').unlink()",
        "from pathlib import Path\nPath('x').rmdir()",
        # Referencing the function is as good as calling it (callbacks, defaults).
        "from pathlib import Path\ndelete = Path.unlink",
        "import os\ndelete = os.remove",
        "from os import remove",
        "from os import unlink as u",
        "from shutil import rmtree",
    ],
)
def test_detector_flags_deletion(snippet: str) -> None:
    assert find_direct_deletes(snippet) != []


def test_detector_allows_list_remove() -> None:
    assert find_direct_deletes("items = [1]\nitems.remove(1)") == []


def test_detector_allows_unrelated_imports() -> None:
    assert find_direct_deletes("from os import replace\nfrom shutil import copy2") == []


def test_project_code_has_no_direct_deletes() -> None:
    offenders = [
        f"{relative}:{line}"
        for folder in SCANNED_DIRS
        if (PROJECT_ROOT / folder).is_dir()
        for path in sorted((PROJECT_ROOT / folder).rglob("*.py"))
        if (relative := path.relative_to(PROJECT_ROOT).as_posix()) not in ALLOWED_TO_DELETE
        for line in find_direct_deletes(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_allowlist_is_exactly_the_purge_module() -> None:
    # Growing this set needs a decision record, not a quiet edit.
    assert frozenset({"src/kresorter/quarantine/purge.py"}) == ALLOWED_TO_DELETE


def test_allowlisted_file_really_deletes() -> None:
    # A stale allowlist entry would be a silent hole: the exempt file must exist and delete.
    for relative in ALLOWED_TO_DELETE:
        assert find_direct_deletes((PROJECT_ROOT / relative).read_text(encoding="utf-8")) != []
