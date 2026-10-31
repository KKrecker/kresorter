"""Console interface. ``safeclean scan`` reports and changes nothing; ``quarantine`` acts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TextIO

from safeclean import cli_quarantine
from safeclean.core.heuristics import JunkClassifier, Platform, default_rules
from safeclean.core.models import Skipped
from safeclean.core.open_files import checker_for_platform
from safeclean.core.policy import PathPolicy
from safeclean.core.scanner import JunkFinding, ScanContext, ScanReport, scan
from safeclean.text import count, format_size

__all__ = [
    "build_parser",
    "default_context",
    "detect_platform",
    "format_size",
    "main",
    "render_json",
    "render_text",
]

_PLATFORMS: dict[str, Platform] = {"win32": "windows", "linux": "linux", "darwin": "darwin"}


def detect_platform(sys_platform: str = sys.platform) -> Platform:
    try:
        return _PLATFORMS[sys_platform]
    except KeyError:
        raise RuntimeError(f"unsupported platform: {sys_platform}") from None


def default_context(
    platform: Platform | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> ScanContext:
    """Context for the current system (arguments exist for tests)."""
    current = platform or detect_platform()
    if current == "windows":
        policy = PathPolicy.for_windows(os.environ if env is None else env)
    else:
        posix: Literal["linux", "darwin"] = "darwin" if current == "darwin" else "linux"
        policy = PathPolicy.for_posix(
            home=PurePosixPath(home or Path.home()),
            platform=posix,
            env=os.environ if env is None else env,
        )
    open_files = checker_for_platform(current)
    return ScanContext(
        policy=policy,
        open_files=open_files,
        classifier=JunkClassifier(default_rules(), platform=current),
        open_files_checked=open_files.reliable,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="safeclean", description="Safe, local file cleanup.")
    commands = parser.add_subparsers(dest="command", required=True)
    scan_cmd = commands.add_parser("scan", help="analyze directories; report only")
    scan_cmd.add_argument("paths", nargs="*", help="directories to scan (default: safe zones)")
    scan_cmd.add_argument("--json", action="store_true", help="machine-readable output")
    scan_cmd.add_argument("--no-hash", action="store_true", help="skip duplicate detection")
    cli_quarantine.add_parser(commands)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
    context_factory: Callable[[], ScanContext] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    context = (context_factory or default_context)()
    if args.command == "quarantine":
        return cli_quarantine.run(args, context, out or sys.stdout, err or sys.stderr)
    roots = [Path(p) for p in args.paths or context.policy.default_roots()]
    report = scan(roots, context, hash_duplicates=not args.no_hash)
    render = render_json if args.json else render_text
    (out or sys.stdout).write(render(report, context.open_files_checked))
    return 0


# --- rendering -----------------------------------------------------------------------------------


def _skip_line(item: Skipped) -> str:
    label = f"{item.reason} ({item.block_reason})" if item.block_reason else str(item.reason)
    detail = f" ({item.detail})" if item.detail else ""
    return f"  {label}: {item.path}{detail}"


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
        lines.append(
            "Note: open-file check is not available yet; "
            "files will be re-checked before any action."
        )
    lines += ["", *_junk_lines(report.junk), "", *_duplicate_lines(report), ""]
    lines.append(f"Skipped: {len(report.skipped)}")
    lines += [_skip_line(item) for item in report.skipped]
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
        "skipped": [
            {
                "path": str(s.path),
                "reason": str(s.reason),
                "block_reason": str(s.block_reason) if s.block_reason else None,
                "detail": s.detail,
            }
            for s in report.skipped
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
