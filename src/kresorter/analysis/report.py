"""Scan report -> one finding per file: level, reasons, quarantine candidate (decision 0010).

Reads nothing from disk. Evidence from junk rules, duplicate decisions and size/age is merged
per path. A copy a duplicate group keeps is never proposed, even when it is junk itself.
Paths are absolute everywhere, in findings and reasons alike.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath

from kresorter.analysis.duplicates import DuplicateDecision, decide
from kresorter.analysis.score import (
    Level,
    Reason,
    assess,
    duplicate_reason,
    junk_reason,
    size_age_reasons,
)
from kresorter.analysis.size_age import Thresholds, find_large_and_old
from kresorter.core.heuristics import JunkClassifier
from kresorter.core.models import FileEntry
from kresorter.core.preflight import Candidate
from kresorter.core.scanner import ScanReport


@dataclass(frozen=True)
class Finding:
    entry: FileEntry
    level: Level
    reasons: tuple[Reason, ...]  # strongest first
    candidate: Candidate  # with the keeper as twin for a duplicate copy
    keeps: str | None  # digest of the duplicate group this file is the kept copy of

    @property
    def proposed(self) -> bool:
        return self.level is not Level.REVIEW and self.keeps is None


@dataclass(frozen=True)
class LevelTotal:
    level: Level
    files: int
    bytes: int


@dataclass(frozen=True)
class AnalysisReport:
    findings: tuple[Finding, ...]  # level, then size (largest first), then path
    duplicates: tuple[DuplicateDecision, ...]
    totals: tuple[LevelTotal, ...]  # one per level, strongest first

    @property
    def proposed(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.proposed)

    @property
    def proposed_bytes(self) -> int:
        return sum(f.entry.size for f in self.proposed)


def analyze(
    report: ScanReport,
    *,
    classifier: JunkClassifier,
    safe_zones: Sequence[PurePath],
    now_ns: int,
    thresholds: Thresholds,
) -> AnalysisReport:
    entries: dict[Path, FileEntry] = {e.path: e for e in report.entries}
    reasons: dict[Path, list[Reason]] = defaultdict(list)
    candidates: dict[Path, Candidate] = {}
    keeps: dict[Path, str] = {}
    for junk in report.junk:
        reasons[junk.entry.path].append(junk_reason(junk.match))
    decisions = tuple(
        decide(g.digest, g.entries, classifier=classifier, safe_zones=safe_zones)
        for g in report.duplicates
    )
    for decision in decisions:
        keeps[decision.keep.path] = decision.digest
        for candidate in decision.remove:
            reasons[candidate.entry.path].append(duplicate_reason(decision))
            candidates[candidate.entry.path] = candidate
    # A file read for junk only is not rated by size or age (decision 0020, item 15).
    for finding in find_large_and_old(report.compared, now_ns=now_ns, thresholds=thresholds):
        reasons[finding.entry.path].extend(size_age_reasons(finding))
    findings: list[Finding] = []
    for path, found in reasons.items():
        assessment = assess(found)
        entry = entries[path]
        candidate = candidates.get(path, Candidate(entry=entry))
        findings.append(
            Finding(entry, assessment.level, assessment.reasons, candidate, keeps.get(path))
        )
    rank = {level: index for index, level in enumerate(Level)}
    findings.sort(key=lambda f: (rank[f.level], -f.entry.size, str(f.entry.path)))
    totals = tuple(
        LevelTotal(
            level,
            files=sum(1 for f in findings if f.level is level),
            bytes=sum(f.entry.size for f in findings if f.level is level),
        )
        for level in Level
    )
    return AnalysisReport(tuple(findings), decisions, totals)
