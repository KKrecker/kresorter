"""``safeclean analyze``: safety levels and reasons for what a scan found (decision 0010).

Read-only, like ``scan``: it walks and hashes, then reports. Nothing is created, moved or
deleted, not even the data directory. Paths are absolute everywhere. With ``--explain`` the
findings are explained after the report (``cli_llm``, decision 0013).
"""

from __future__ import annotations

import argparse
import json
from typing import Any, TextIO

from safeclean import cli_llm
from safeclean.analysis.report import AnalysisReport, Finding
from safeclean.analysis.run import analyze_paths
from safeclean.analysis.score import Level
from safeclean.analysis.size_age import Thresholds
from safeclean.core.scanner import ScanContext, ScanReport
from safeclean.llm.explain import Explanations
from safeclean.text import OPEN_FILES_NOTE, count, format_size, skip_json, skip_line

MIB = 1024**2

_TITLES = {
    Level.SAFE: "Safe",
    Level.LIKELY_SAFE: "Likely safe",
    Level.REVIEW: "Review (never proposed)",
}


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1: {value}")
    return value


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    default = Thresholds()
    analyze_cmd = commands.add_parser("analyze", help="rate what a scan finds; report only")
    analyze_cmd.add_argument(
        "paths", nargs="*", help="directories to analyze (default: safe zones)"
    )
    analyze_cmd.add_argument("--json", action="store_true", help="machine-readable output")
    analyze_cmd.add_argument(
        "--large",
        type=positive_int,
        default=default.large_bytes // MIB,
        metavar="MIB",
        help="report files of at least this many MiB for review (default: %(default)s)",
    )
    analyze_cmd.add_argument(
        "--older-than",
        type=positive_int,
        default=default.old_after_days,
        metavar="DAYS",
        help="report files unmodified for this many days for review (default: %(default)s)",
    )
    cli_llm.add_explain(analyze_cmd)


def run(
    args: argparse.Namespace,
    context: ScanContext,
    out: TextIO,
    err: TextIO,
    explainer: cli_llm.Explainer | None = None,
) -> int:
    thresholds = Thresholds(large_bytes=args.large * MIB, old_after_days=args.older_than)
    scanned, analysis = analyze_paths(args.paths, context, thresholds)
    explained = cli_llm.ask(explainer, analysis.findings)  # in the order both outputs show
    checked = context.open_files_checked
    if args.json:
        out.write(render_json(scanned, analysis, thresholds, checked, explained))
    else:
        out.write(render_text(scanned, analysis, thresholds, checked) + cli_llm.section(explained))
    cli_llm.notify(explained, err)
    return 0


# --- rendering ---------------------------------------------------------------------------------


def finding_lines(finding: Finding) -> list[str]:
    kept = "" if finding.keeps is None else "  (kept copy, not proposed)"
    lines = [f"  {finding.entry.path}  {format_size(finding.entry.size)}{kept}"]
    lines += [f"    {r.evidence}: {r.detail}" for r in finding.reasons]
    return lines


def _level_lines(analysis: AnalysisReport) -> list[str]:
    lines: list[str] = []
    for total in analysis.totals:
        files = f"{count(total.files, 'file')}, {format_size(total.bytes)}"
        lines.append(f"{_TITLES[total.level]}: {files}")
        for finding in analysis.findings:
            if finding.level is total.level:
                lines += finding_lines(finding)
        lines.append("")
    return lines


def render_text(
    scanned: ScanReport, analysis: AnalysisReport, thresholds: Thresholds, checked: bool
) -> str:
    proposed = f"{count(len(analysis.proposed), 'file')}, {format_size(analysis.proposed_bytes)}"
    lines = [
        "safeclean analyze - report only, nothing was changed",
        f"Roots: {', '.join(str(r) for r in scanned.roots)}",
        f"Scanned: {count(scanned.files_scanned, 'file')}, {format_size(scanned.bytes_scanned)}",
    ]
    if not checked:
        lines.append(OPEN_FILES_NOTE)
    lines += ["", *_level_lines(analysis), f"Proposed for quarantine: {proposed}", ""]
    lines.append(f"Skipped: {len(scanned.skipped)}")
    lines += [skip_line(item) for item in scanned.skipped]
    return "\n".join(lines) + "\n"


def _finding_json(finding: Finding) -> dict[str, Any]:
    twin = finding.candidate.twin
    return {
        "path": str(finding.entry.path),
        "size": finding.entry.size,
        "level": str(finding.level),
        "proposed": finding.proposed,
        "kept_copy": finding.keeps is not None,
        "twin": None if twin is None else str(twin.path),
        "reasons": [{"evidence": str(r.evidence), "detail": r.detail} for r in finding.reasons],
    }


def render_json(
    scanned: ScanReport,
    analysis: AnalysisReport,
    thresholds: Thresholds,
    checked: bool,
    explained: Explanations | None = None,
) -> str:
    data: dict[str, Any] = {
        "roots": [str(r) for r in scanned.roots],
        "files_scanned": scanned.files_scanned,
        "bytes_scanned": scanned.bytes_scanned,
        "open_file_check": checked,
        "thresholds": {
            "large_bytes": thresholds.large_bytes,
            "old_after_days": thresholds.old_after_days,
        },
        "findings": [_finding_json(f) for f in analysis.findings],
        "duplicates": [
            {
                "digest": d.digest,
                "keep": str(d.keep.path),
                "keep_reason": str(d.reason),
                "remove": [str(c.entry.path) for c in d.remove],
            }
            for d in analysis.duplicates
        ],
        "totals": [
            {"level": str(t.level), "files": t.files, "bytes": t.bytes} for t in analysis.totals
        ],
        "proposed": {"files": len(analysis.proposed), "bytes": analysis.proposed_bytes},
        "skipped": [skip_json(s) for s in scanned.skipped],
        **cli_llm.json_keys(explained),
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
