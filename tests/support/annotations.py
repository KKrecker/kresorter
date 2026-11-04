"""What failed, where anyone can read it: on CI each place tests fail at becomes an annotation
of the job, which GitHub shows on a public repository without signing in, while it shows its
logs only to those who are (decision 0015, item 20).

A failure's place is where its error was raised, so the tests that one fault fails are one
annotation: how many, the first error and the tests with theirs. A step keeps ten errors: the
nine places most tests fail at, then one that counts the rest.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

LIMIT = 10  # the errors GitHub keeps for a step
NAMED = 20  # the tests an annotation names
WIDE = 300  # the characters of an error it shows


@dataclass(frozen=True)
class Failure:
    test: str
    error: str  # the first line of its message
    place: str  # where it was raised, ``path:line`` from the repository's root


def failure(test: str, longrepr: object, root: str) -> Failure:
    """The failure of ``test`` from pytest's ``longrepr``: its crash, else its last line."""
    crash = getattr(longrepr, "reprcrash", None)
    if crash is None:
        lines = str(longrepr).strip().splitlines() or [""]
        return Failure(test, lines[-1].strip(), "")
    message = str(crash.message).strip().splitlines() or [""]
    path = str(crash.path).removeprefix(root).lstrip("\\/").replace("\\", "/")
    return Failure(test, message[0], f"{path}:{crash.lineno}")


def failures(stats: Mapping[str, Sequence[Any]], root: str) -> list[Failure]:
    """The failures of a run from pytest's ``stats``: the tests failed, then those in error."""
    reports = [report for kind in ("failed", "error") for report in stats.get(kind, [])]
    return [failure(report.nodeid, report.longrepr, root) for report in reports]


def _data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _property(text: str) -> str:
    return _data(text).replace(":", "%3A").replace(",", "%2C")


def _cut(text: str) -> str:
    return text if len(text) <= WIDE else text[: WIDE - 3] + "..."


def commands(failures: Sequence[Failure]) -> list[str]:
    """The workflow commands ``::error`` of ``failures``, the place most fail at first."""
    places: dict[str, list[Failure]] = {}
    for one in failures:
        places.setdefault(one.place, []).append(one)
    ranked = sorted(places.items(), key=lambda item: -len(item[1]))
    shown = ranked if len(ranked) <= LIMIT else ranked[: LIMIT - 1]
    found: list[str] = []
    for place, theirs in shown:
        title = f"{len(theirs)} failed at {place or 'no place'}: {_cut(theirs[0].error)}"
        lines = [f"{one.test}: {_cut(one.error)}" for one in theirs[:NAMED]]
        if len(theirs) > NAMED:
            lines.append(f"and {len(theirs) - NAMED} more")
        found.append(f"::error title={_property(title)}::{_data(chr(10).join(lines))}")
    rest = ranked[len(shown) :]
    if rest:
        count = sum(len(theirs) for _, theirs in rest)
        lines = [
            f"{len(theirs)} at {place or 'no place'}: {_cut(theirs[0].error)}"
            for place, theirs in rest
        ]
        title = f"{count} failed at {len(rest)} more places"
        found.append(f"::error title={_property(title)}::{_data(chr(10).join(lines))}")
    return found
