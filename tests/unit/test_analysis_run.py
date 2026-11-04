"""Scan and analysis of the paths asked for, for the CLI and the window (decision 0014, 12)."""

from pathlib import Path

from kresorter.analysis.run import analyze_paths
from kresorter.analysis.score import Level
from kresorter.analysis.size_age import Thresholds
from kresorter.core.scanner import ScanContext
from support.files import snapshot, write


def test_without_paths_the_safe_zones_are_analyzed(scan: ScanContext, zone: Path) -> None:
    # [0014.12]
    write(zone / "proj" / "__pycache__" / "m.cpython-313.pyc", b"bytecode")
    before = snapshot(zone)

    scanned, analysis = analyze_paths([], scan, Thresholds())

    assert scanned.files_scanned == 1
    assert [(f.entry.path.name, f.level) for f in analysis.findings] == [
        ("m.cpython-313.pyc", Level.LIKELY_SAFE)
    ]
    assert snapshot(zone) == before


def test_the_paths_given_are_analyzed_instead(
    scan: ScanContext, zone: Path, tmp_path: Path
) -> None:
    # [0014.12]
    write(zone / "a" / "notes.txt", b"hello")
    write(zone / "b" / "notes.txt", b"other")

    scanned, _ = analyze_paths([str(zone / "b")], scan, Thresholds())

    assert [entry.path for entry in scanned.entries] == [zone / "b" / "notes.txt"]


def test_the_scan_s_progress_is_passed_on(scan: ScanContext, zone: Path) -> None:
    # [0018.16] For the window's scan.
    write(zone / "a" / "notes.txt", b"hello")
    read: list[int] = []
    analyze_paths([], scan, Thresholds(), progress=read.append)
    assert read == [1]
