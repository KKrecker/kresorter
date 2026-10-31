"""Safety levels with their reasons (decision 0010, items 11-13).

No number: three levels, a pinned level per kind of evidence, and the level of a finding is
that of its strongest evidence. "Large" and "old" are ``REVIEW`` evidence, so they never raise
a level. All reasons are kept, strongest first, so ``REVIEW`` findings explain themselves.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from safeclean.analysis.duplicates import DuplicateDecision
from safeclean.analysis.size_age import SizeAgeFinding, SizeAgeReason
from safeclean.core.heuristics import JunkCategory, JunkMatch
from safeclean.text import format_size


class Level(StrEnum):
    """Strongest first."""

    SAFE = "safe"
    LIKELY_SAFE = "likely_safe"
    REVIEW = "review"


class Evidence(StrEnum):
    JUNK_CACHE = "junk_cache"
    JUNK_THUMBNAILS = "junk_thumbnails"
    JUNK_OS_METADATA = "junk_os_metadata"
    JUNK_TEMP = "junk_temp"
    JUNK_CRASH_DUMP = "junk_crash_dump"
    DUPLICATE_COPY = "duplicate_copy"
    LARGE = "large"
    OLD = "old"


_LEVELS: dict[Evidence, Level] = {
    Evidence.JUNK_CACHE: Level.SAFE,
    Evidence.JUNK_THUMBNAILS: Level.SAFE,
    Evidence.JUNK_OS_METADATA: Level.SAFE,
    Evidence.JUNK_TEMP: Level.LIKELY_SAFE,
    Evidence.JUNK_CRASH_DUMP: Level.LIKELY_SAFE,
    Evidence.DUPLICATE_COPY: Level.LIKELY_SAFE,
    Evidence.LARGE: Level.REVIEW,
    Evidence.OLD: Level.REVIEW,
}
_JUNK: dict[JunkCategory, Evidence] = {
    JunkCategory.CACHE: Evidence.JUNK_CACHE,
    JunkCategory.THUMBNAILS: Evidence.JUNK_THUMBNAILS,
    JunkCategory.OS_METADATA: Evidence.JUNK_OS_METADATA,
    JunkCategory.TEMP: Evidence.JUNK_TEMP,
    JunkCategory.CRASH_DUMP: Evidence.JUNK_CRASH_DUMP,
}
_RANK = {level: rank for rank, level in enumerate(Level)}
_ORDER = {evidence: index for index, evidence in enumerate(Evidence)}


@dataclass(frozen=True)
class Reason:
    evidence: Evidence
    detail: str = ""  # rule id, the copy that stays, size or age: shown to the user


@dataclass(frozen=True)
class Assessment:
    level: Level
    reasons: tuple[Reason, ...]  # strongest first, each once

    @property
    def proposed(self) -> bool:
        """Only SAFE and LIKELY_SAFE are proposed for quarantine; REVIEW is information."""
        return self.level is not Level.REVIEW


def level_of(evidence: Evidence) -> Level:
    return _LEVELS[evidence]


def junk_reason(match: JunkMatch) -> Reason:
    return Reason(_JUNK[match.category], match.rule_id)


def duplicate_reason(decision: DuplicateDecision) -> Reason:
    return Reason(Evidence.DUPLICATE_COPY, str(decision.keep.path))


def size_age_reasons(finding: SizeAgeFinding) -> tuple[Reason, ...]:
    details = {
        SizeAgeReason.LARGE: (Evidence.LARGE, format_size(finding.entry.size)),
        SizeAgeReason.OLD: (Evidence.OLD, f"unmodified for {finding.age_days} days"),
    }
    return tuple(Reason(*details[reason]) for reason in finding.reasons)


def assess(reasons: Iterable[Reason]) -> Assessment:
    def key(reason: Reason) -> tuple[int, int, str]:
        return (_RANK[level_of(reason.evidence)], _ORDER[reason.evidence], reason.detail)

    ordered = tuple(sorted(set(reasons), key=key))
    if not ordered:
        raise ValueError("an assessment needs at least one piece of evidence")
    return Assessment(level_of(ordered[0].evidence), ordered)
