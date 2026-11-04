"""Scan the paths asked for and rate what was found, for the CLI and the window (decision 0014,
item 12). Read-only: it walks and hashes, nothing is created, moved or deleted."""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from kresorter.analysis.report import AnalysisReport, analyze
from kresorter.analysis.size_age import Thresholds
from kresorter.core.scanner import Progress, ScanContext, ScanReport, scan, unreported

__all__ = ["analyze_paths"]


def analyze_paths(
    paths: Sequence[str],
    context: ScanContext,
    thresholds: Thresholds,
    *,
    progress: Progress = unreported,
) -> tuple[ScanReport, AnalysisReport]:
    """Scan ``paths`` (default: the safe zones) and rate what was found; ``progress``: the
    scan's (decision 0018, item 16)."""
    roots = [Path(p) for p in paths or context.policy.default_roots()]
    scanned = scan(roots, context, hash_duplicates=True, progress=progress)
    analysis = analyze(
        scanned,
        classifier=context.classifier,
        safe_zones=context.policy.default_roots(),
        now_ns=time.time_ns(),
        thresholds=thresholds,
    )
    return scanned, analysis
