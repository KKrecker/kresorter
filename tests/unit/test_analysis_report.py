"""Scan report -> one finding per file with its level, reasons and quarantine candidate.

``analyze`` merges the evidence of junk rules, duplicate decisions and size/age into one
finding per path (decision 0010). It reads nothing from disk. Paths are absolute everywhere,
in findings and in reasons alike, so the user sees the same path on every line. A copy that a
duplicate group keeps is never proposed, even when it is junk itself: a group never loses all
its copies.
"""

import os
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy
from kresorter.analysis.report import AnalysisReport, Finding, LevelTotal, analyze
from kresorter.analysis.score import Evidence, Level, Reason
from kresorter.analysis.size_age import DAY_NS, Thresholds
from kresorter.core.heuristics import load_rules
from kresorter.core.models import FileEntry
from kresorter.core.preflight import Candidate
from kresorter.core.scanner import ScanContext, scan
from kresorter.organize.synced import NoSyncedFolders
from support.files import snapshot
from support.host import host_classifier

RULES = """
[[rule]]
id = "cachedir"
category = "thumbnails"
description = "thumbnails, safe: a cache is likely safe (decision 0018, item 19)"
dirs = ["cache"]

[[rule]]
id = "tmp-ext"
category = "temp"
description = "temp"
files = ["*.tmp"]
"""
CLASSIFIER = host_classifier(load_rules(RULES))
NOW = 1_700_000_000_000_000_000
RECENT = NOW - DAY_NS
THRESHOLDS = Thresholds(large_bytes=1000, old_after_days=365)


def write(path: Path, data: bytes, mtime_ns: int = RECENT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def entry(path: Path) -> FileEntry:
    info = path.lstat()
    return FileEntry(path=path, size=info.st_size, mtime_ns=info.st_mtime_ns)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "root"


def run(tmp_path: Path, root: Path) -> AnalysisReport:
    context = ScanContext(
        policy=make_policy(tmp_path),
        open_files=FakeOpenFiles(),
        classifier=CLASSIFIER,
        open_files_checked=True,
        platform="linux",
        synced=NoSyncedFolders(),
    )
    return analyze(
        scan([root], context),
        classifier=CLASSIFIER,
        safe_zones=[root / "Downloads"],
        now_ns=NOW,
        thresholds=THRESHOLDS,
    )


def by_path(report: AnalysisReport) -> dict[Path, Finding]:
    return {f.entry.path: f for f in report.findings}


# --- one kind of evidence ----------------------------------------------------------------------


def test_junk_becomes_a_safe_finding_with_a_plain_candidate(tmp_path: Path, root: Path) -> None:
    junk = write(root / "proj" / "cache" / "blob", b"cached")
    write(root / "notes.txt", b"keep me")

    report = run(tmp_path, root)

    assert report.findings == (
        Finding(
            entry=entry(junk),
            level=Level.SAFE,
            reasons=(Reason(Evidence.JUNK_THUMBNAILS, "cachedir"),),
            candidate=Candidate(entry=entry(junk)),
            keeps=None,
        ),
    )
    assert report.findings[0].proposed is True


def test_duplicate_copies_are_candidates_twinned_with_the_keeper(
    tmp_path: Path, root: Path
) -> None:
    keep = write(root / "Photos" / "a.jpg", b"same bytes", NOW - 2 * DAY_NS)
    copy = write(root / "Downloads" / "a.jpg", b"same bytes")

    report = run(tmp_path, root)

    (finding,) = report.findings  # the keeper has no evidence of its own: not a finding
    assert finding.entry == entry(copy)
    assert finding.level is Level.LIKELY_SAFE
    assert finding.reasons == (Reason(Evidence.DUPLICATE_COPY, str(keep)),)
    assert finding.candidate.twin == entry(keep)
    assert finding.candidate.digest == report.duplicates[0].digest
    assert report.duplicates[0].keep == entry(keep)


def test_large_or_old_alone_is_review_and_not_proposed(tmp_path: Path, root: Path) -> None:
    big_old = write(root / "disk.img", b"x" * 1000, NOW - 400 * DAY_NS)

    (finding,) = run(tmp_path, root).findings

    assert finding.entry == entry(big_old)
    assert finding.level is Level.REVIEW
    assert [r.evidence for r in finding.reasons] == [Evidence.LARGE, Evidence.OLD]
    assert finding.proposed is False


def test_files_without_evidence_are_not_findings(tmp_path: Path, root: Path) -> None:
    write(root / "a.txt", b"a")
    write(root / "b.txt", b"b")
    assert run(tmp_path, root).findings == ()


# --- merging -----------------------------------------------------------------------------------


def test_junk_and_duplicate_evidence_merge_into_one_finding(tmp_path: Path, root: Path) -> None:
    keep = write(root / "work" / "a.tmp.bak", b"same bytes", NOW - 2 * DAY_NS)
    copy = write(root / "work" / "a.tmp", b"same bytes")

    (finding,) = run(tmp_path, root).findings

    assert finding.entry == entry(copy)
    assert finding.reasons == (
        Reason(Evidence.JUNK_TEMP, "tmp-ext"),
        Reason(Evidence.DUPLICATE_COPY, str(keep)),
    )
    # The twin stays attached: preflight also checks the keeper, the stricter of the two.
    assert finding.candidate.twin == entry(keep)


def test_a_kept_copy_is_never_proposed_even_when_it_is_junk(tmp_path: Path, root: Path) -> None:
    first = write(root / "cache" / "a.bin", b"same bytes", NOW - 2 * DAY_NS)
    second = write(root / "cache" / "b.bin", b"same bytes")

    report = run(tmp_path, root)

    findings = by_path(report)
    assert findings[first].keeps == report.duplicates[0].digest
    assert findings[first].proposed is False  # the last copy is never suggested for removal
    assert findings[second].keeps is None
    assert findings[second].proposed is True
    assert [f.entry.path for f in report.proposed] == [second]


# --- paths are the same everywhere -------------------------------------------------------------


def test_the_path_in_a_duplicate_reason_is_the_keeper_finding_path(
    tmp_path: Path, root: Path
) -> None:
    first = write(root / "cache" / "a.bin", b"same bytes", NOW - 2 * DAY_NS)
    second = write(root / "cache" / "b.bin", b"same bytes")

    findings = by_path(run(tmp_path, root))

    (reason,) = [r for r in findings[second].reasons if r.evidence is Evidence.DUPLICATE_COPY]
    assert reason.detail == str(findings[first].entry.path)
    assert Path(reason.detail).is_absolute()
    assert all(f.entry.path.is_absolute() for f in findings.values())


# --- order and totals --------------------------------------------------------------------------


def test_findings_are_ordered_by_level_then_size_then_path(tmp_path: Path, root: Path) -> None:
    small_cache = write(root / "cache" / "s", b"1")
    big_cache = write(root / "cache" / "b", b"1234")
    temp_b = write(root / "b.tmp", b"12")
    temp_a = write(root / "a.tmp", b"34")
    review = write(root / "old.txt", b"o", NOW - 400 * DAY_NS)

    report = run(tmp_path, root)

    expected = [big_cache, small_cache, temp_a, temp_b, review]
    assert [f.entry.path for f in report.findings] == expected


def test_totals_per_level_and_proposed_bytes(tmp_path: Path, root: Path) -> None:
    write(root / "cache" / "s", b"1")
    write(root / "cache" / "b", b"1234")
    write(root / "a.tmp", b"12")
    write(root / "old.txt", b"o", NOW - 400 * DAY_NS)

    report = run(tmp_path, root)

    assert report.totals == (
        LevelTotal(Level.SAFE, files=2, bytes=5),
        LevelTotal(Level.LIKELY_SAFE, files=1, bytes=2),
        LevelTotal(Level.REVIEW, files=1, bytes=1),
    )
    assert report.proposed_bytes == 7


# --- read-only ---------------------------------------------------------------------------------


def test_analyze_never_touches_the_disk(tmp_path: Path, root: Path) -> None:
    write(root / "cache" / "a.bin", b"same bytes")
    write(root / "cache" / "b.bin", b"same bytes")
    write(root / "x.tmp", b"t", NOW - 400 * DAY_NS)
    before = snapshot(root)

    run(tmp_path, root)

    assert snapshot(root) == before
