"""The two READMEs side by side (decision 0019, items 15 and 16): the switch under each title,
the headings' levels in order, the code blocks, the images and the link targets, read as GitHub
reads them; a link to a heading of the page is that heading's place, its anchor being GitHub's."""

import re
from collections.abc import Sequence

from support.markdown import headings

SWITCHES = {
    "README.md": "**English** | [Русский](README.ru.md)",
    "README.ru.md": "[English](README.md) | **Русский**",
}
LINK = re.compile(r"(!?)\[[^\]]*\]\(([^)\s]+)\)")
PUNCTUATION = re.compile(r"[^\w\- ]")


def slug(title: str) -> str:
    """The anchor GitHub gives a heading: lower-cased, its punctuation dropped, a space a hyphen."""
    return PUNCTUATION.sub("", title.lower()).replace(" ", "-")


def prose(text: str) -> str:
    """The lines outside code blocks, the switches left out."""
    kept: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line not in SWITCHES.values():
            kept.append(line)
    return "\n".join(kept)


def fences(text: str) -> list[list[str]]:
    """Every code block, its fences included, in order."""
    found: list[list[str]] = []
    inside: list[str] | None = None
    for line in text.splitlines():
        if inside is None:
            if line.startswith("```"):
                inside = [line]
        else:
            inside.append(line)
            if line.startswith("```"):
                found.append(inside)
                inside = None
    return found


def levels(text: str) -> list[int]:
    """The level of each heading, in order."""
    return [level for level, _, _ in headings(text)]


def images(text: str) -> list[str]:
    """The target of each image, in order."""
    return [target for bang, target in LINK.findall(prose(text)) if bang]


def links(text: str) -> list[str]:
    """The target of each link but the switch, in order; one to a heading of the page is ``#``
    and that heading's place among them, counted from 0, or ``#?`` and the anchor when no heading
    has it."""
    places = {slug(title): place for place, (_, title, _) in enumerate(headings(text))}
    found: list[str] = []
    for bang, target in LINK.findall(prose(text)):
        if bang:
            continue
        if target.startswith("#"):
            place = places.get(target[1:])
            target = f"#{place}" if place is not None else f"#?{target[1:]}"
        found.append(target)
    return found


def _first(what: str, english: Sequence[object], russian: Sequence[object]) -> list[str]:
    """Where ``english`` and ``russian`` part, if they do."""
    for place in range(max(len(english), len(russian))):
        ours = english[place] if place < len(english) else None
        theirs = russian[place] if place < len(russian) else None
        if ours != theirs:
            return [f"{what} differ at {place}: {ours!r} in README.md, {theirs!r} in README.ru.md"]
    return []


def differences(english: str, russian: str) -> list[str]:
    """What keeps ``russian`` from saying what ``english`` says, as item 15 names it; nothing
    when the two agree."""
    found: list[str] = []
    for name, text in (("README.md", english), ("README.ru.md", russian)):
        lines = text.splitlines()
        if not (lines[:1] and lines[0].startswith("# ") and lines[1:3] == ["", SWITCHES[name]]):
            found.append(f"{name} does not begin, under its title, with {SWITCHES[name]}")
        broken = [target[2:] for target in links(text) if target.startswith("#?")]
        found += [f"{name}: no heading has the anchor {anchor}" for anchor in broken]
    found += _first("the headings' levels", levels(english), levels(russian))
    found += _first("the code blocks", fences(english), fences(russian))
    found += _first("the images", images(english), images(russian))
    found += _first("the link targets", links(english), links(russian))
    return found
