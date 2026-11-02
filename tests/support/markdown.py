"""Markdown as the README and the roadmap are read: a heading outside a code block, a section up
to the next heading of its level or above, the code blocks of a language."""

import re

HEADING = re.compile(r"(#+) (.+)")


def headings(text: str) -> list[tuple[int, str, int]]:
    """Each heading outside code blocks: its level, its title and its line's index."""
    found: list[tuple[int, str, int]] = []
    fenced = False
    for index, line in enumerate(text.splitlines()):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (heading := HEADING.fullmatch(line)):
            found.append((len(heading[1]), heading[2], index))
    return found


def section(text: str, title: str) -> list[str]:
    """The lines under ``title`` up to the next heading of its level or above."""
    lines, marks = text.splitlines(), headings(text)
    starts = [(level, index) for level, name, index in marks if name == title]
    assert len(starts) == 1, f"{title!r} is a heading {len(starts)} times"
    level, start = starts[0]
    ends = [index for other, _, index in marks if index > start and other <= level]
    return lines[start + 1 : min(ends, default=len(lines))]


def blocks(lines: list[str], language: str) -> list[list[str]]:
    """The code blocks of ``language``, each its lines without the fences."""
    found: list[list[str]] = []
    inside: list[str] | None = None
    for line in lines:
        if inside is None and line == "```" + language:
            inside = []
        elif inside is not None and line == "```":
            found.append(inside)
            inside = None
        elif inside is not None:
            inside.append(line)
    return found
