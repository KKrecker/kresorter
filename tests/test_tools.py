"""The development tools are pinned, and the build backend has PEP 639 (decision 0015, item 19).

The extra ``dev`` pins each tool to one version, and PySide6 to the one CI tests, which the
range of the extra ``ui`` allows; PyInstaller is pinned beside the Windows build and Inno
Setup in the workflow. A tool changes in a commit of its own.
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==(\d+(?:\.\d+)*)")
TOOLS = {"ruff", "mypy", "pytest", "pytest-cov", "pytest-qt", "build", "hatchling"}
QT = "PySide6-Essentials"


def pyproject() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def extra(name: str) -> list[str]:
    project = pyproject()["project"]
    assert isinstance(project, dict)
    found = project["optional-dependencies"][name]
    assert isinstance(found, list)
    return found


def pins(lines: list[str]) -> dict[str, str]:
    """Each line as ``name==version``; a line that is not one fails the test."""
    found: dict[str, str] = {}
    for line in lines:
        match = PIN.fullmatch(line)
        assert match is not None, line
        found[match.group(1)] = match.group(2)
    return found


def test_every_development_tool_is_pinned_to_one_version() -> None:
    # [0015.19]
    assert set(pins(extra("dev"))) == TOOLS | {QT}


def test_the_tests_run_one_qt_that_the_window_allows() -> None:
    # [0015.19] the extra ui keeps its range; dev pins a version inside it
    assert extra("ui") == [f"{QT}>=6.8,<7"]
    major, minor, *_ = (int(part) for part in pins(extra("dev"))[QT].split("."))
    assert major == 6
    assert minor >= 8


def test_the_build_backend_has_pep_639() -> None:
    # [0015.19] license-files and an SPDX expression need hatchling 1.27
    system = pyproject()["build-system"]
    assert isinstance(system, dict)
    assert system["requires"] == ["hatchling>=1.27,<2"]
    assert system["build-backend"] == "hatchling.build"


def test_pyinstaller_is_pinned_beside_the_windows_build() -> None:
    # [0015.19]
    text = (ROOT / "packaging" / "windows" / "requirements.txt").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert {name.lower() for name in pins(lines)} == {"pyinstaller", "pyinstaller-hooks-contrib"}


def test_inno_setup_is_pinned_in_the_workflow() -> None:
    # [0015.19]
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r'^  INNO_SETUP_VERSION: "\d+\.\d+\.\d+"$', workflow, re.MULTILINE)
