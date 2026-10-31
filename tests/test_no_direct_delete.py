"""Safety guard: no direct file deletion anywhere in project code (see decision 0001).

Complements ruff's banned-api, which cannot see method calls such as ``Path.unlink()``.
"""

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCANNED_DIRS = ("src", "tests", "scripts")

# Method names that delete regardless of the receiver.
FORBIDDEN_METHODS = frozenset({"unlink", "rmdir", "rmtree", "removedirs"})
# Names forbidden only on these modules (``list.remove`` is fine).
FORBIDDEN_MODULE_ATTRS = {"os": frozenset({"remove", "unlink", "rmdir", "removedirs"})}


def find_direct_deletes(source: str) -> list[int]:
    """Return line numbers of direct deletion calls in ``source``."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        receiver = node.func.value
        module_attrs = (
            FORBIDDEN_MODULE_ATTRS.get(receiver.id, frozenset())
            if isinstance(receiver, ast.Name)
            else frozenset()
        )
        if attr in FORBIDDEN_METHODS or attr in module_attrs:
            lines.append(node.lineno)
    return lines


@pytest.mark.parametrize(
    "snippet",
    [
        "import os\nos.remove('x')",
        "import os\nos.unlink('x')",
        "import shutil\nshutil.rmtree('x')",
        "from pathlib import Path\nPath('x').unlink()",
        "from pathlib import Path\nPath('x').rmdir()",
    ],
)
def test_detector_flags_deletion(snippet: str) -> None:
    assert find_direct_deletes(snippet) != []


def test_detector_allows_list_remove() -> None:
    assert find_direct_deletes("items = [1]\nitems.remove(1)") == []


def test_project_code_has_no_direct_deletes() -> None:
    offenders = [
        f"{path.relative_to(PROJECT_ROOT)}:{line}"
        for folder in SCANNED_DIRS
        if (PROJECT_ROOT / folder).is_dir()
        for path in sorted((PROJECT_ROOT / folder).rglob("*.py"))
        for line in find_direct_deletes(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
