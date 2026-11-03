"""The README's quarantine section on the systems it acts on (decision 0016, item 11).

The quarantine needs a reliable open-file check: Linux and Windows have one, and on macOS its
commands refuse; one sentence says what the Windows check cannot see.
"""

import re
from pathlib import Path

from support.markdown import section

ROOT = Path(__file__).resolve().parents[1]


def sentences() -> list[str]:
    """The section's prose, outside its code blocks, sentence by sentence."""
    lines = section((ROOT / "README.md").read_text(encoding="utf-8"), "Quarantine")
    prose: list[str] = []
    fenced = False
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced:
            prose.append(line)
    return [s for s in re.split(r"(?<=\.)\s+", " ".join(prose).strip()) if s]


def test_linux_and_windows_check_open_files_and_macos_refuses() -> None:
    # [0016.11]
    [said] = [s for s in sentences() if "open-file check" in s]
    assert "Linux and Windows have one" in said
    assert "on macOS these commands refuse (exit code 3)" in said


def test_one_sentence_says_what_the_windows_check_cannot_see() -> None:
    # [0016.11] the limitation decision 0016 accepts
    [said] = [s for s in sentences() if s.startswith("On Windows")]
    assert "attributes" in said
    assert "mapped into memory" in said
