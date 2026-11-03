"""CI checks on two systems (decision 0015, item 20).

The checks run on ``ubuntu-latest`` for every Python of the matrix, and on ``windows-latest``
for the oldest and the newest while the repository is private; every push is checked, a step's
branch too. Qt's system libraries are installed on Linux only; the window's tests run offscreen
on both. The checkout is the same on both: the files keep their LF line endings on Windows.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHONS = ["3.11", "3.12", "3.13", "3.14"]
SYSTEMS = ["ubuntu-latest", "windows-latest"]
WINDOWS = {"3.11", "3.14"}  # while the repository is private


def workflow() -> list[str]:
    return (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8").splitlines()


def indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def block(lines: list[str], key: str) -> list[str]:
    """The lines under ``key:`` (the one line that is exactly it), up to the next line that is
    indented as much or less; comments and blank lines are left out."""
    lines = [line for line in lines if line.strip() and not line.strip().startswith("#")]
    (start,) = [i for i, line in enumerate(lines) if line.strip() == f"{key}:"]
    found: list[str] = []
    for line in lines[start + 1 :]:
        if indent(line) <= indent(lines[start]):
            break
        found.append(line)
    return found


def value(lines: list[str], key: str) -> str:
    """The value of ``key`` among the outermost lines of a block."""
    top = min(indent(line) for line in lines)
    (found,) = [
        line.split(":", 1)[1].strip()
        for line in lines
        if indent(line) == top and line.strip().startswith(f"{key}:")
    ]
    return found


def listed(text: str) -> list[str]:
    assert text.startswith("[")
    assert text.endswith("]")
    return [item.strip().strip('"') for item in text[1:-1].split(",")]


def combinations() -> set[tuple[str, str]]:
    """(system, Python) of every job of the check, the matrix less what it excludes."""
    matrix = block(block(workflow(), "check"), "matrix")
    systems = listed(value(matrix, "os"))
    pythons = listed(value(matrix, "python-version"))
    excluded: set[tuple[str, str]] = set()
    entries = "\n".join(block(matrix, "exclude")).split("- ")[1:]
    for entry in entries:
        pairs = dict(re.findall(r"([a-z-]+): *\"?([^\"\n]+)\"?", entry))
        excluded.add((pairs["os"], pairs["python-version"]))
    return {(s, p) for s in systems for p in pythons} - excluded


def test_linux_for_every_python_and_windows_for_the_oldest_and_the_newest() -> None:
    # [0015.20]
    found = combinations()
    assert {p for s, p in found if s == "ubuntu-latest"} == set(PYTHONS)
    assert {p for s, p in found if s == "windows-latest"} == WINDOWS
    assert {s for s, _ in found} == set(SYSTEMS)
    assert value(block(workflow(), "check"), "runs-on") == "${{ matrix.os }}"


def test_one_failing_job_stops_no_other() -> None:
    # [0015.20] what fails on one system is seen with what fails on the other
    assert value(block(workflow(), "strategy"), "fail-fast") == "false"


def test_every_push_is_checked_a_step_s_branch_too() -> None:
    # [0015.20]
    assert [line.strip() for line in block(workflow(), "on")] == ["push:", "pull_request:"]


def test_qt_s_system_libraries_are_installed_on_linux_only() -> None:
    # [0015.20]
    lines = workflow()
    (apt,) = [i for i, line in enumerate(lines) if "apt-get install" in line]
    assert lines[apt - 1].strip() == "if: runner.os == 'Linux'"
    assert lines[apt - 2].strip() == "- name: Qt's system libraries"
    assert sum("if:" in line for line in lines) == 1  # every other step runs on both


def test_the_window_s_tests_run_offscreen_on_both_systems() -> None:
    # [0015.20] set for the job, not for a step or a system
    job = block(workflow(), "check")
    assert value(block(job, "env"), "QT_QPA_PLATFORM") == "offscreen"


def test_the_checkout_keeps_lf_line_endings_on_windows() -> None:
    # [0015.20] a file read as bytes, hashed or packed is the same on both systems
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "* text=auto eol=lf" in attributes
