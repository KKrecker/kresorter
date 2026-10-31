"""Large and old files: evidence for review, never a proposal on its own (decision 0010).

Pure: decides on scanned entries and an injected ``now_ns``. Age is ``mtime_ns`` only;
``atime`` is unreliable under ``noatime``/``relatime``. An ``mtime`` in the future (clock skew,
restored backups) is no evidence of age: such a file is never old.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from safeclean.core.models import FileEntry

DAY_NS = 86_400 * 1_000_000_000
_MIB = 1024**2


class SizeAgeReason(StrEnum):
    LARGE = "large"
    OLD = "old"


@dataclass(frozen=True)
class Thresholds:
    large_bytes: int = 500 * _MIB  # inclusive
    old_after_days: int = 730  # inclusive: unmodified for at least this many days

    def __post_init__(self) -> None:
        if self.large_bytes < 1 or self.old_after_days < 1:
            raise ValueError("thresholds must be positive")


@dataclass(frozen=True)
class SizeAgeFinding:
    entry: FileEntry
    reasons: tuple[SizeAgeReason, ...]  # in SizeAgeReason order
    age_days: int  # whole days since mtime; 0 for an mtime in the future


def find_large_and_old(
    entries: Iterable[FileEntry], *, now_ns: int, thresholds: Thresholds
) -> tuple[SizeAgeFinding, ...]:
    findings: list[SizeAgeFinding] = []
    for entry in sorted(entries, key=lambda e: str(e.path)):
        age_ns = max(0, now_ns - entry.mtime_ns)
        reasons: list[SizeAgeReason] = []
        if entry.size >= thresholds.large_bytes:
            reasons.append(SizeAgeReason.LARGE)
        if age_ns >= thresholds.old_after_days * DAY_NS:
            reasons.append(SizeAgeReason.OLD)
        if reasons:
            findings.append(SizeAgeFinding(entry, tuple(reasons), age_ns // DAY_NS))
    return tuple(findings)
