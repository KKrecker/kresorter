"""The changelog says what a release has (decision 0015, item 18).

``## [Unreleased]`` comes first, above ``## [0.1.0] - YYYY-MM-DD``, the latest version, which is
``__version__`` and what the release job checks a tag against. 0.1.0's entries, under Keep a
Changelog's categories, are what the release does for its users: one for each command and one
for each page of the window, each said once, and not the development's log, which stays in git
and in the roadmap. No Qt is needed here.
"""

import argparse
import re
from pathlib import Path

import release

import kresorter
from kresorter.cli import build_parser
from kresorter.ui.texts import CATALOG
from support.markdown import headings, section

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")
PAGES = ("overview", "findings", "organize", "autostart", "quarantine", "settings")
VERSION = f"[{kresorter.__version__}]"


def changelog() -> str:
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def release_heading() -> str:
    (title,) = [title for level, title, _ in headings(changelog()) if title.startswith(VERSION)]
    return title


def entries() -> list[str]:
    """The entries of the release: each list item, its continuation lines joined to it."""
    found: list[str] = []
    for line in section(changelog(), release_heading()):
        if line.startswith("- "):
            found.append(line[2:])
        elif line.startswith("  ") and found:
            found[-1] += " " + line.strip()
    return found


def commands() -> list[str]:
    parser = build_parser()
    (action,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    return list(action.choices)


def test_unreleased_comes_first_above_the_release_of_version() -> None:
    # [0015.18]
    found = [title for level, title, _ in headings(changelog()) if level == 2]
    assert found[0] == "[Unreleased]"
    assert found[1] == release_heading()
    assert re.fullmatch(r"\[\d+\.\d+\.\d+\] - \d{4}-\d{2}-\d{2}", release_heading())


def test_the_latest_version_is_version_as_the_release_job_reads_it() -> None:
    # [0015.18] [0015.23]
    assert release.latest(changelog()) == kresorter.__version__
    source = (ROOT / "src" / "kresorter" / "__init__.py").read_text(encoding="utf-8")
    assert release.check(f"v{kresorter.__version__}", source, changelog()) == (
        kresorter.__version__
    )


def test_the_release_s_entries_are_in_keep_a_changelog_s_categories() -> None:
    # [0015.18]
    lines = section(changelog(), release_heading())
    found = [line.removeprefix("### ") for line in lines if line.startswith("### ")]
    assert found
    assert set(found) <= set(CATEGORIES)
    assert len(found) == len(set(found))
    assert [line for line in lines if line.startswith("#") and not line.startswith("### ")] == []


def test_one_entry_for_each_command() -> None:
    # [0015.18] the entry starts with the command
    for command in commands():
        said = [entry for entry in entries() if entry.startswith(f"`kresorter {command}")]
        assert len(said) == 1, command


def test_one_entry_for_each_page_of_the_window() -> None:
    # [0015.18] by the window's English name, in the sidebar's order
    names = [CATALOG[f"page.{page}"]["en"] for page in PAGES]
    places: list[int] = []
    for name in names:
        said = [i for i, entry in enumerate(entries()) if entry.startswith(f"The **{name}** page")]
        assert len(said) == 1, name
        places += said
    assert places == sorted(places)


def test_not_the_development_s_log() -> None:
    # [0015.18] no decision, audit or refactor is the users' business, nor the TDD's pairs
    text = " ".join(entries()).lower()
    for words in ("decision 00", "audit", "refactor", "(red)", "(green)", "pending"):
        assert words not in text, words
    assert len(entries()) <= 30
