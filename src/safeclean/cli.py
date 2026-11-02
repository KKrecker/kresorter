"""Console interface. ``scan``, ``analyze``, ``autostart list`` report; ``llm status`` checks;
the others can act."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from safeclean import (
    cli_analyze,
    cli_autostart,
    cli_llm,
    cli_organize,
    cli_quarantine,
    cli_recover,
)
from safeclean.core.scanner import JunkFinding, ScanReport, scan
from safeclean.environment import Environment
from safeclean.text import OPEN_FILES_NOTE, count, format_size, skip_json, skip_line

__all__ = [
    "build_parser",
    "format_size",
    "main",
    "render_json",
    "render_text",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="safeclean", description="Safe, local file cleanup.")
    commands = parser.add_subparsers(dest="command", required=True)
    scan_cmd = commands.add_parser("scan", help="analyze directories; report only")
    scan_cmd.add_argument("paths", nargs="*", help="directories to scan (default: safe zones)")
    scan_cmd.add_argument("--json", action="store_true", help="machine-readable output")
    scan_cmd.add_argument("--no-hash", action="store_true", help="skip duplicate detection")
    cli_analyze.add_parser(commands)
    cli_quarantine.add_parser(commands)
    cli_organize.add_parser(commands)
    cli_autostart.add_parser(commands)
    cli_recover.add_parser(commands)
    cli_llm.add_parser(commands)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
    environment: Environment | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    system = Environment() if environment is None else environment
    if args.command == "llm":
        return cli_llm.run_status(system.llm_env, out or sys.stdout, system.llm_limits)
    explainer = (
        cli_llm.Explainer(system.llm_env, system.llm_limits)
        if getattr(args, "explain", False)
        else None
    )
    if args.command in ("autostart", "recover"):  # autostart list needs no scan context
        listing_context = system.autostart_context()
        factory = system.scan_context  # built only by the commands that act
        if args.command == "recover" or args.action == "recover":  # one command, an alias
            return cli_recover.run(listing_context, factory(), out or sys.stdout, err or sys.stderr)
        return cli_autostart.run(
            args, listing_context, factory, out or sys.stdout, err or sys.stderr, explainer
        )
    cli_quarantine.check_usage(parser, args)
    context = system.scan_context()
    if args.command == "analyze":
        return cli_analyze.run(args, context, out or sys.stdout, err or sys.stderr, explainer)
    if args.command == "quarantine":
        return cli_quarantine.run(args, context, out or sys.stdout, err or sys.stderr)
    if args.command == "organize":
        return cli_organize.run(args, context, out or sys.stdout, err or sys.stderr, explainer)
    roots = [Path(p) for p in args.paths or context.policy.default_roots()]
    report = scan(roots, context, hash_duplicates=not args.no_hash)
    render = render_json if args.json else render_text
    (out or sys.stdout).write(render(report, context.open_files_checked))
    return 0


# --- rendering -----------------------------------------------------------------------------------


def _junk_lines(junk: Sequence[JunkFinding]) -> list[str]:
    total = sum(f.entry.size for f in junk)
    lines = [f"Junk candidates: {count(len(junk), 'file')}, {format_size(total)}"]
    by_category: dict[str, list[JunkFinding]] = defaultdict(list)
    for finding in junk:
        by_category[finding.match.category].append(finding)
    for category, items in by_category.items():
        size = format_size(sum(f.entry.size for f in items))
        lines.append(f"  {category}: {count(len(items), 'file')}, {size}")
        lines += [
            f"    {f.entry.path}  [{f.match.rule_id}]  {format_size(f.entry.size)}" for f in items
        ]
    return lines


def _duplicate_lines(report: ScanReport) -> list[str]:
    wasted = format_size(sum(g.wasted_bytes for g in report.duplicates))
    lines = [f"Duplicate groups: {len(report.duplicates)} (wasted {wasted})"]
    for group in report.duplicates:
        lines.append(f"  {group.digest[:12]}  {len(group.paths)} x {format_size(group.size)}")
        lines += [f"    {path}" for path in group.paths]
    return lines


def render_text(report: ScanReport, open_files_checked: bool) -> str:
    lines = [
        "safeclean scan - report only, nothing was changed",
        f"Roots: {', '.join(str(r) for r in report.roots)}",
        f"Scanned: {count(report.files_scanned, 'file')}, {format_size(report.bytes_scanned)}",
    ]
    if not open_files_checked:
        lines.append(OPEN_FILES_NOTE)
    lines += ["", *_junk_lines(report.junk), "", *_duplicate_lines(report), ""]
    lines.append(f"Skipped: {len(report.skipped)}")
    lines += [skip_line(item) for item in report.skipped]
    return "\n".join(lines) + "\n"


def render_json(report: ScanReport, open_files_checked: bool) -> str:
    data: dict[str, Any] = {
        "roots": [str(r) for r in report.roots],
        "files_scanned": report.files_scanned,
        "bytes_scanned": report.bytes_scanned,
        "open_file_check": open_files_checked,
        "junk": [
            {
                "path": str(f.entry.path),
                "rule_id": f.match.rule_id,
                "category": str(f.match.category),
                "size": f.entry.size,
            }
            for f in report.junk
        ],
        "duplicates": [
            {"digest": g.digest, "size": g.size, "paths": [str(p) for p in g.paths]}
            for g in report.duplicates
        ],
        "skipped": [skip_json(s) for s in report.skipped],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
