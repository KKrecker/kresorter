"""Scanner: wires policy + walker + heuristics + hashing into a report. Read-only."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy
from kresorter.core import hashing
from kresorter.core.heuristics import JunkCategory, load_rules
from kresorter.core.models import FileEntry, Skipped, SkipReason
from kresorter.core.open_files import ProcFdChecker
from kresorter.core.policy import BlockReason
from kresorter.core.scanner import DuplicateGroup, ScanContext, scan
from kresorter.organize.synced import NoSyncedFolders
from support.files import write
from support.host import host_classifier

RULES = """
[[rule]]
id = "tmp-ext"
category = "temp"
description = "Temporary file"
files = ["*.tmp"]
"""


def context(tmp_path: Path, *blocked: Path) -> ScanContext:
    return ScanContext(
        policy=make_policy(tmp_path, *blocked),
        open_files=FakeOpenFiles(),
        classifier=host_classifier(load_rules(RULES)),
        open_files_checked=True,
        platform="linux",
        synced=NoSyncedFolders(),
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


def entry(path: Path) -> FileEntry:
    info = path.lstat()
    return FileEntry(path=path, size=info.st_size, mtime_ns=info.st_mtime_ns)


def test_identical_files_form_a_duplicate_group(tmp_path: Path) -> None:
    root = tmp_path / "root"
    a = write(root / "a.bin", b"same bytes")
    b = write(root / "sub" / "b.bin", b"same bytes")
    write(root / "c.bin", b"diff bytes")

    report = scan([root], context(tmp_path))

    assert report.duplicates == (
        DuplicateGroup(digest=hashing.hash_file(a), entries=(entry(a), entry(b))),
    )
    group = report.duplicates[0]
    assert group.paths == (a, b)
    assert group.size == 10
    assert group.wasted_bytes == 10


def test_duplicate_entries_carry_the_scanned_metadata(tmp_path: Path) -> None:
    # Size and mtime_ns as scanned: what a quarantine Candidate and its twin are checked against.
    root = tmp_path / "root"
    a = write(root / "a.bin", b"same bytes")
    b = write(root / "b.bin", b"same bytes")
    os.utime(a, ns=(1, 1_000_000_000_000_000_000))
    os.utime(b, ns=(1, 1_200_000_000_000_000_000))

    (group,) = scan([root], context(tmp_path)).duplicates

    assert [(e.path, e.size, e.mtime_ns) for e in group.entries] == [
        (a, 10, 1_000_000_000_000_000_000),
        (b, 10, 1_200_000_000_000_000_000),
    ]


def test_the_report_keeps_every_scanned_entry(tmp_path: Path) -> None:
    # Analysis needs all of them: large and old files are not junk or duplicates.
    root = tmp_path / "root"
    a = write(root / "a.txt", b"12345")
    b = write(root / "x.tmp", b"abc")

    report = scan([root], context(tmp_path))

    assert sorted(report.entries, key=lambda e: e.path) == [entry(a), entry(b)]


def test_a_duplicate_group_needs_two_copies(tmp_path: Path) -> None:
    one = FileEntry(path=tmp_path / "a.bin", size=10, mtime_ns=1)
    with pytest.raises(ValueError, match="at least two"):
        DuplicateGroup(digest="d", entries=(one,))


def test_a_duplicate_group_has_one_size(tmp_path: Path) -> None:
    a = FileEntry(path=tmp_path / "a.bin", size=10, mtime_ns=1)
    b = FileEntry(path=tmp_path / "b.bin", size=11, mtime_ns=1)
    with pytest.raises(ValueError, match="size"):
        DuplicateGroup(digest="d", entries=(a, b))


def test_duplicates_can_be_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    write(root / "a.bin", b"same")
    write(root / "b.bin", b"same")
    calls: list[Path] = []

    def spy(path: Path, **kwargs: object) -> str:
        calls.append(path)
        return ""

    monkeypatch.setattr(hashing, "hash_file", spy)

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


def test_a_scan_lists_the_open_files_of_every_process_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0018.11] At its start, not per file: the file held then is open for the scan.
    root = tmp_path / "root"
    held = write(root / "held.bin", b"h")
    files = [write(root / f"f{n}.bin", bytes([n])) for n in range(5)]
    proc = tmp_path / "proc"
    (proc / "123" / "fd").mkdir(parents=True)
    (proc / "123" / "fd" / "3").symlink_to(held)
    listed: list[Path] = []
    real_scandir = os.scandir

    def scandir(path: str | Path) -> object:
        listed.append(Path(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    report = scan([root], replace(context(tmp_path), open_files=ProcFdChecker(proc)))
    assert [e.path for e in report.entries] == files
    assert report.skipped == (
        Skipped(path=held, reason=SkipReason.BLOCKED, block_reason=BlockReason.OPEN_FILE),
    )
    assert listed.count(proc) == 1


def test_a_scan_without_a_list_of_processes_finds_every_file_open(tmp_path: Path) -> None:
    # [0018.11] Fail closed.
    root = tmp_path / "root"
    files = [write(root / f"f{n}.bin", bytes([n])) for n in range(2)]
    checker = ProcFdChecker(tmp_path / "no-proc")
    report = scan([root], replace(context(tmp_path), open_files=checker))
    assert report.entries == ()
    assert [(s.path, s.block_reason) for s in report.skipped] == [
        (path, BlockReason.OPEN_FILE) for path in files
    ]


def test_a_scan_reports_the_files_read_so_far(tmp_path: Path) -> None:
    # [0018.16] At least every 1,000 files, and at the end.
    root = tmp_path / "root"
    for n in range(2500):
        write(root / f"d{n % 3}" / f"f{n}.bin", b"")
    read: list[int] = []
    report = scan([root], context(tmp_path), hash_duplicates=False, progress=read.append)
    assert report.files_scanned == 2500
    assert read[-1] == 2500
    assert read == sorted(set(read))
    assert all(after - before <= 1000 for before, after in zip([0, *read], read, strict=False))


def test_an_empty_scan_reports_its_end(tmp_path: Path) -> None:
    # [0018.16]
    read: list[int] = []
    (tmp_path / "root").mkdir()
    scan([tmp_path / "root"], context(tmp_path), progress=read.append)
    assert read == [0]
