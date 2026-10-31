"""Scanner: wires policy + walker + heuristics + hashing into a report. Read-only."""

from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy
from safeclean.core import hashing
from safeclean.core.heuristics import JunkCategory, JunkClassifier, load_rules
from safeclean.core.models import Skipped, SkipReason
from safeclean.core.policy import BlockReason
from safeclean.core.scanner import DuplicateGroup, ScanContext, scan

RULES = """
[[rule]]
id = "tmp-ext"
category = "temp"
description = "Temporary file"
files = ["*.tmp"]
"""


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def context(tmp_path: Path, *blocked: Path) -> ScanContext:
    return ScanContext(
        policy=make_policy(tmp_path, *blocked),
        open_files=FakeOpenFiles(),
        classifier=JunkClassifier(load_rules(RULES), platform="linux"),
        open_files_checked=True,
    )


def test_report_counts_files_junk_and_skips(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write(root / "a.txt", b"12345")
    junk = write(root / "x.tmp", b"abc")
    write(root / "sys" / "kernel.bin", b"k")

    report = scan([root], context(tmp_path, root / "sys"))

    assert report.roots == (root,)
    assert report.files_scanned == 2
    assert report.bytes_scanned == 8
    assert [(f.entry.path, f.match.rule_id, f.match.category) for f in report.junk] == [
        (junk, "tmp-ext", JunkCategory.TEMP)
    ]
    assert report.skipped == (
        Skipped(path=root / "sys", reason=SkipReason.BLOCKED, block_reason=BlockReason.SYSTEM),
    )


def test_identical_files_form_a_duplicate_group(tmp_path: Path) -> None:
    root = tmp_path / "root"
    a = write(root / "a.bin", b"same bytes")
    b = write(root / "sub" / "b.bin", b"same bytes")
    write(root / "c.bin", b"diff bytes")

    report = scan([root], context(tmp_path))

    assert report.duplicates == (
        DuplicateGroup(digest=hashing.hash_file(a), size=10, paths=(a, b)),
    )
    assert report.duplicates[0].wasted_bytes == 10


def test_duplicates_can_be_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    write(root / "a.bin", b"same")
    write(root / "b.bin", b"same")
    calls: list[Path] = []
    monkeypatch.setattr(hashing, "hash_file", lambda path, **kw: calls.append(path) or "")

    report = scan([root], context(tmp_path), hash_duplicates=False)

    assert report.duplicates == ()
    assert calls == []


def test_hashing_failures_are_reported_as_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    a = write(root / "a.bin", b"same")
    b = write(root / "b.bin", b"same")

    def deny(path: Path, **kwargs: object) -> str:
        raise PermissionError(13, "denied")

    monkeypatch.setattr(hashing, "hash_file", deny)

    report = scan([root], context(tmp_path))

    assert report.duplicates == ()
    assert report.skipped == (
        Skipped(path=a, reason=SkipReason.PERMISSION_DENIED),
        Skipped(path=b, reason=SkipReason.PERMISSION_DENIED),
    )
