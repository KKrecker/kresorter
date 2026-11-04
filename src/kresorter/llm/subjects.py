"""What one explanation is about: the facts of a final result, nothing else (decision 0013).

Items 17 and 18. A subject is ``kind`` and then a fixed, ordered list of facts per kind, each
string cleaned and cut (``llm.clean``). Nothing else of a result leaves: not its path, folder,
size, times, digest, location, whole command, notes or details. Equal facts are one subject.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from kresorter.analysis.report import Finding
from kresorter.analysis.score import Evidence, Reason
from kresorter.autostart.models import AutostartItem
from kresorter.llm.clean import cleaned_fact, one_line
from kresorter.organize.planner import Stay

Fact = str | bool | tuple[str, ...]
Result = Finding | AutostartItem | Stay

EXTENSION_CHARACTERS = 16
_JUNK = frozenset(
    {
        Evidence.JUNK_CACHE,
        Evidence.JUNK_BROWSER_CACHE,
        Evidence.JUNK_THUMBNAILS,
        Evidence.JUNK_OS_METADATA,
        Evidence.JUNK_TEMP,
        Evidence.JUNK_CRASH_DUMP,
    }
)
_SEPARATOR = re.compile(r"[/\\]")


@dataclass(frozen=True)
class Subject:
    """``kind`` first, then the facts of its kind in order: equal facts, one subject."""

    pairs: tuple[tuple[str, Fact], ...]

    @property
    def facts(self) -> dict[str, Fact]:
        return dict(self.pairs)


def subject_of(result: Result) -> Subject:
    """The subject of one result, by a pure function of it."""
    if isinstance(result, Finding):
        return Subject(
            (
                ("kind", "finding"),
                ("level", cleaned_fact(result.level)),
                ("reasons", tuple(_reason(reason) for reason in result.reasons)),
                ("extension", _extension(result.entry.path.name)),
            )
        )
    if isinstance(result, AutostartItem):
        return Subject(
            (
                ("kind", "autostart"),
                ("source", cleaned_fact(result.source)),
                ("scope", cleaned_fact(result.scope)),
                ("name", cleaned_fact(result.name)),
                ("program", cleaned_fact(_program(result.command))),
                ("enabled", result.enabled),
            )
        )
    return Subject(
        (
            ("kind", "stay"),
            ("reason", cleaned_fact(result.reason)),
            ("extension", _extension(result.path.name)),
        )
    )


def subjects(results: Iterable[Result]) -> tuple[Subject, ...]:
    """One subject per set of facts, in the order each first appears (item 18)."""
    return tuple(dict.fromkeys(subject_of(result) for result in results))


def _reason(reason: Reason) -> str:
    """The evidence, and for junk also its rule id."""
    if reason.evidence in _JUNK:
        return cleaned_fact(f"{reason.evidence}:{reason.detail}")
    return cleaned_fact(reason.evidence)


def _extension(name: str) -> str:
    """The lower-cased suffix of the cleaned name: empty when none or over 16 characters."""
    shown = one_line(name)
    dot = shown.rfind(".")
    suffix = shown[dot:].lower() if dot > 0 else ""
    return suffix if 1 < len(suffix) <= EXTENSION_CHARACTERS else ""


def _program(command: str) -> str:
    """The last component of the first word, or of the quoted part the command starts with."""
    text = one_line(command)
    if text[:1] in ('"', "'"):
        end = text.find(text[0], 1)
        first = text[1:] if end == -1 else text[1:end]
    else:
        first = text.split(" ", 1)[0]
    return _SEPARATOR.split(first)[-1]
