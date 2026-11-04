"""The security audit's report (decision 0018, item 36).

``docs/reviews/security-audit.md`` says what was checked, area by area (the network, text
shown, file operations, the data directory, parsing, the model's answers, packaging), what was
found and what was fixed, each fix with its test: a test the report names exists.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "reviews" / "security-audit.md"
AREAS = (
    "The network",
    "Text shown",
    "File operations",
    "The data directory",
    "Parsing",
    "The model's answers",
    "Packaging",
)
TEST = re.compile(r"`(tests/[\w/]+\.py)::(\w+)`")


def _sections(text: str) -> dict[str, str]:
    """Each ``### `` section of the report: its title, its text."""
    parts = re.split(r"^### (.+)$", text, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_the_report_says_what_was_checked_in_each_area() -> None:
    # [0018.36]
    rows = [
        line.split("|")[1].strip()
        for line in REPORT.read_text(encoding="utf-8").splitlines()
        if line[:1] == "|"
    ]
    assert [area for area in AREAS if area not in rows] == []


def test_each_fix_names_its_test_and_the_test_exists() -> None:
    # [0018.36]
    text = REPORT.read_text(encoding="utf-8")
    fixes = {title: body for title, body in _sections(text).items() if title.startswith("F")}
    assert fixes
    assert [title for title, body in fixes.items() if not TEST.search(body)] == []
    named = TEST.findall(text)
    missing = [
        f"{path}::{name}"
        for path, name in named
        if not (ROOT / path).is_file()
        or f"def {name}(" not in (ROOT / path).read_text(encoding="utf-8")
    ]
    assert missing == []
