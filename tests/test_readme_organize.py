"""The README's organize on the systems it moves files on (decision 0017, item 14).

Organize moves files on Linux and Windows, not on macOS; on Windows it refuses the folders a
sync client keeps and leaves a file whose new path would pass 259 characters. The window's
Organize page refuses where the command does.
"""

import re
from pathlib import Path

from support.markdown import section

ROOT = Path(__file__).resolve().parents[1]


def sentences(title: str) -> list[str]:
    """The prose of the section ``title``, outside its code blocks, sentence by sentence."""
    lines = section((ROOT / "README.md").read_text(encoding="utf-8"), title)
    prose: list[str] = []
    fenced = False
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced:
            prose.append(line)
    return [s for s in re.split(r"(?<=\.)\s+", " ".join(prose).strip()) if s]


def test_organize_moves_files_on_linux_and_windows_and_macos_refuses() -> None:
    # [0017.14]
    [said] = [s for s in sentences("Organize") if "moves files on" in s]
    assert "on Linux and Windows" in said
    assert "on macOS" in said
    assert "refuse (exit code 3)" in said
    assert not [s for s in sentences("Organize") if "macOS and Windows" in s]


def test_on_windows_synced_folders_are_refused_and_no_path_passes_the_limit() -> None:
    # [0017.14]
    [said] = [s for s in sentences("Organize") if s.startswith("On Windows")]
    assert "sync client" in said
    assert "259 characters" in said


def test_the_window_s_page_refuses_where_the_command_does() -> None:
    # [0017.14] the Organize bullet of the desktop app
    [said] = [s for s in sentences("Desktop app (optional)") if "the page says why" in s]
    assert "(macOS, or no reliable open-file check)" in said
