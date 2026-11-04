"""What failed, where anyone can read it: on CI the failures become annotations of the job,
which GitHub shows on a public repository without signing in, while it shows its logs only to
those who are (decision 0015, item 20).

A failure's place is where its error was raised, so the tests that one fault fails are one
block: how many, the first test's traceback, a line a frame, and its error, then the tests.
The blocks, the place most tests fail at first, fill the ten annotations GitHub keeps for a
step, each as long as it shows; what does not fit is counted at the end of the last. When the
coverage is under 100 %, the first annotation says where: the rows of its report under it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

LIMIT = 10  # the errors GitHub keeps for a step
SIZE = 4000  # the characters of an annotation it shows, a little less
BLOCK = 1800  # the characters of a place's block, so that two fit in one
RESERVE = 400  # what the last annotation keeps for the places that did not fit
NAMED = 20  # the tests a block names
WIDE = 300  # the characters of a line
DEPTH = 6  # the frames of a traceback


@dataclass(frozen=True)
class Failure:
    test: str
    error: str  # the first line of its message
    place: str  # where it was raised, ``path:line`` from the repository's root
    detail: str = ""  # the traceback, ``path:line: source`` a frame, then the error's lines


def _relative(path: object, root: str) -> str:
    return str(path).removeprefix(root).lstrip("\\/").replace("\\", "/")


def _cut(text: str, wide: int = WIDE) -> str:
    return text if len(text) <= wide else text[: wide - 3] + "..."


def _detail(longrepr: object, root: str) -> str:
    entries = getattr(getattr(longrepr, "reprtraceback", None), "reprentries", None) or []
    lines: list[str] = []
    for entry in entries[-DEPTH:]:
        where = getattr(entry, "reprfileloc", None)
        source = [line for line in getattr(entry, "lines", []) if line.startswith(">")]
        if where is not None:
            code = f": {source[0][1:].strip()}" if source else ""
            lines.append(_cut(f"{_relative(where.path, root)}:{where.lineno}{code}"))
    if entries:
        error = [line for line in getattr(entries[-1], "lines", []) if line.startswith("E")]
        lines.extend(_cut(line[1:].strip()) for line in error)
    return "\n".join(lines)


def failure(test: str, longrepr: object, root: str) -> Failure:
    """The failure of ``test`` from pytest's ``longrepr``: its crash, else its last line."""
    crash = getattr(longrepr, "reprcrash", None)
    if crash is None:
        lines = str(longrepr).strip().splitlines() or [""]
        return Failure(test, lines[-1].strip(), "")
    message = str(crash.message).strip().splitlines() or [""]
    place = f"{_relative(crash.path, root)}:{crash.lineno}"
    return Failure(test, message[0], place, _detail(longrepr, root))


def failures(stats: Mapping[str, Sequence[Any]], root: str) -> list[Failure]:
    """The failures of a run from pytest's ``stats``: the tests failed, then those in error."""
    reports = [report for kind in ("failed", "error") for report in stats.get(kind, [])]
    return [failure(report.nodeid, report.longrepr, root) for report in reports]


def uncovered(report: str) -> list[str]:
    """The rows of a coverage report ``term-missing`` under 100 %: ``name cover missing``."""
    rows: list[str] = []
    for line in report.splitlines():
        words = line.split()
        covers = [index for index, word in enumerate(words) if word.endswith("%")]
        if covers and words[covers[0]] != "100%":
            name, (cover, *missing) = words[0].replace("\\", "/"), words[covers[0] :]
            rows.append(_cut(" ".join([name, cover, *missing]), SIZE // 4))
    return rows


def _data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _property(text: str) -> str:
    return _data(text).replace(":", "%3A").replace(",", "%2C")


def _heading(place: str, theirs: Sequence[Failure]) -> str:
    return _cut(f"{len(theirs)} failed at {place or 'no place'}: {theirs[0].error}")


def _block(place: str, theirs: Sequence[Failure]) -> str:
    lines = [f"== {_heading(place, theirs)}"]
    if theirs[0].detail:
        lines.append(theirs[0].detail)
    lines.extend(_cut(one.test, WIDE // 2) for one in theirs[:NAMED])
    if len(theirs) > NAMED:
        lines.append(f"and {len(theirs) - NAMED} more")
    return _cut("\n".join(lines), BLOCK)


def commands(failures: Sequence[Failure], short: Sequence[str] = ()) -> list[str]:
    """The workflow commands ``::error`` of ``failures``, the place most fail at first, after
    the rows ``short`` of the coverage report under 100 %."""
    coverage = [(f"coverage under 100 % in {len(short)} rows", [*short])] if short else []
    limit = LIMIT - len(coverage)
    places: dict[str, list[Failure]] = {}
    for one in failures:
        places.setdefault(one.place, []).append(one)
    ranked = sorted(places.items(), key=lambda item: -len(item[1]))
    filled: list[tuple[str, list[str]]] = []  # an annotation's title and blocks
    size = 0
    left = list(ranked)
    while left:
        place, theirs = left[0]
        block = _block(place, theirs)
        room = SIZE - RESERVE if len(filled) == limit else SIZE
        if filled and size + len(block) + 1 <= room:
            filled[-1][1].append(block)
            size += len(block) + 1
        elif len(filled) < limit:
            filled.append((_heading(place, theirs), [block]))
            size = len(block)
        else:
            break
        left.pop(0)
    if left:
        count = sum(len(theirs) for _, theirs in left)
        rest = ", ".join(place or "no place" for place, _ in left)
        filled[-1][1].append(
            _cut(f"and {count} failed at {len(left)} more places: {rest}", RESERVE)
        )
    return [
        f"::error title={_property(title)}::{_data(_cut(chr(10).join(blocks), SIZE))}"
        for title, blocks in coverage + filled
    ]
