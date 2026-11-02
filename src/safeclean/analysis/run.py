"""Scan the paths asked for and rate what was found, for the CLI and the window (decision 0014,
item 12). Read-only: it walks and hashes, nothing is created, moved or deleted."""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from safeclean.analysis.report import AnalysisReport, analyze
from safeclean.analysis.size_age import Thresholds
from safeclean.core.scanner import ScanContext, ScanReport, scan

__all__ = ["analyze_paths"]


def analyze_paths(
    paths: Sequence[str], context: ScanContext, thresholds: Thresholds
) -> tuple[ScanReport, AnalysisReport]:
    """Scan ``paths`` (default: the safe zones) and rate what was found."""
    roots = [Path(p) for p in paths or context.policy.default_roots()]
    scanned = scan(roots, context, hash_duplicates=True)
    analysis = analyze(
        scanned,
        classifier=context.classifier,
        safe_zones=context.policy.default_roots(),
        now_ns=time.time_ns(),
        thresholds=thresholds,
    )
    return scanned, analysis
