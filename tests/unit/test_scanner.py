"""Scanner: wires policy + walker + heuristics + hashing into a report. Read-only."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy
from kresorter.core import hashing
from kresorter.core.hashing import Digests
from kresorter.core.heuristics import JunkCategory, load_rules
from kresorter.core.models import FileEntry, Skipped, SkipReason
from kresorter.core.open_files import ProcFdChecker, ShareModeChecker
from kresorter.core.policy import BlockReason
from kresorter.core.scanner import DuplicateGroup, ScanContext, ScanTimes, scan
from kresorter.organize.synced import NoSyncedFolders
from support.files import write
from support.host import host_classifier
from support.kernel import SideBySideKernel

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


def open_skip(path: Path) -> Skipped:
    return Skipped(path=path, reason=SkipReason.BLOCKED, block_reason=BlockReason.OPEN_FILE)


def test_a_scan_lists_the_open_files_of_every_process_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0018.11] [0020.17] Once the copies are hashed, not per file: the copy held then is open
    # for the scan and leaves its group.
    root = tmp_path / "root"
    held = write(root / "held.bin", b"same")
    copies = [write(root / f"f{n}.bin", b"same") for n in range(3)]
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
    assert [e.path for e in report.entries] == copies
    assert [group.paths for group in report.duplicates] == [tuple(copies)]
    assert report.skipped == (open_skip(held),)
    assert listed.count(proc) == 1


def test_a_scan_without_a_list_of_processes_finds_the_junk_and_the_copies_open(
    tmp_path: Path,
) -> None:
    # [0018.11] [0020.17] Fail closed; the other files are not asked about.
    root = tmp_path / "root"
    a, b = write(root / "a.bin", b"same"), write(root / "b.bin", b"same")
    junk, other = write(root / "x.tmp", b"junk"), write(root / "y.txt", b"other")
    checker = ProcFdChecker(tmp_path / "no-proc")
    report = scan([root], replace(context(tmp_path), open_files=checker))
    assert [e.path for e in report.entries] == [other]
    assert (report.files_scanned, report.bytes_scanned) == (1, 5)
    assert (report.junk, report.duplicates) == ((), ())
    assert report.skipped == (open_skip(junk), open_skip(a), open_skip(b))


def test_a_scan_lists_without_opening_a_file_then_asks_about_the_junk_and_the_copies(
    tmp_path: Path,
) -> None:
    # [0020.17] Once the junk is classified and the duplicates hashed; a large or old file is
    # asked about when it is acted on (preflight), a junk copy once.
    root = tmp_path / "root"
    a, b = write(root / "a.bin", b"same"), write(root / "b.bin", b"same")
    junk, twin = write(root / "x.tmp", b"twin"), write(root / "y.tmp", b"twin")
    write(root / "large.iso", b"large")
    checker = FakeOpenFiles()
    report = scan([root], replace(context(tmp_path), open_files=checker))
    assert checker.calls == [junk, twin, a, b]
    assert report.files_scanned == 5


def test_an_open_copy_leaves_its_group_and_a_group_left_with_one_copy_is_none(
    tmp_path: Path,
) -> None:
    # [0020.17] An open file is skipped as before: no entry, no junk, no copy.
    root = tmp_path / "root"
    a, b, c = (write(root / f"{n}.bin", b"three") for n in "abc")
    d, e = write(root / "d.bin", b"two"), write(root / "e.bin", b"two")
    junk = write(root / "x.tmp", b"junk")
    checker = FakeOpenFiles([b, d, junk])
    report = scan([root], replace(context(tmp_path), open_files=checker))
    assert [group.paths for group in report.duplicates] == [(a, c)]
    assert report.junk == ()
    assert [entry.path for entry in report.entries] == [a, c, e]
    assert report.skipped == (open_skip(junk), open_skip(b), open_skip(d))


def test_the_share_mode_checks_of_the_copies_run_side_by_side_their_answers_in_order(
    tmp_path: Path,
) -> None:
    # [0018.12] [0020.17] Up to eight at once; each file's answer is its own, whichever check
    # ends first.
    root = tmp_path / "root"
    paths = [write(root / f"f{n:02}.bin") for n in range(16)]
    held = {paths[3].name, paths[12].name}
    kernel = SideBySideKernel(parties=8, held=held)
    report = scan([root], replace(context(tmp_path), open_files=ShareModeChecker(kernel)))
    kept = tuple(p for p in paths if p.name not in held)
    assert [group.paths for group in report.duplicates] == [kept]
    assert report.skipped == (open_skip(paths[3]), open_skip(paths[12]))
    assert kernel.most == 8


def test_a_scan_with_nothing_to_ask_about_lists_no_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0020.17] No junk, no copies: no question.
    root, proc = tmp_path / "root", tmp_path / "proc"
    write(root / "a.txt", b"a")
    (proc / "123" / "fd").mkdir(parents=True)
    listed: list[Path] = []
    real_scandir = os.scandir

    def scandir(path: str | Path) -> object:
        listed.append(Path(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    report = scan([root], replace(context(tmp_path), open_files=ProcFdChecker(proc)))
    assert [e.path for e in report.entries] == [root / "a.txt"]
    assert listed == [root]


def test_a_scan_says_how_long_it_took_and_what_took_it(tmp_path: Path) -> None:
    # [0020.19] Listing (and classifying), duplicates, then the open-file checks.
    root = tmp_path / "root"
    write(root / "a.bin", b"same")
    write(root / "b.bin", b"same")
    ticks = iter([100.0, 102.1, 109.4, 109.8])
    times = scan([root], context(tmp_path), clock=lambda: next(ticks)).times
    parts = (times.total, times.listing, times.open_checks, times.duplicates)
    assert parts == pytest.approx((9.8, 2.1, 0.4, 7.3))


def test_a_scan_s_times_are_measured(tmp_path: Path) -> None:
    # [0020.19] by default on the monotonic clock: none negative, the parts within the whole.
    root = tmp_path / "root"
    write(root / "a.bin", b"same")
    write(root / "b.bin", b"same")
    times = scan([root], context(tmp_path)).times
    parts = (times.listing, times.open_checks, times.duplicates)
    assert min(parts) >= 0
    assert sum(parts) <= times.total + 1e-9


def test_a_report_made_without_a_scan_took_no_time() -> None:
    # [0020.19]
    assert ScanTimes() == ScanTimes(total=0.0, listing=0.0, open_checks=0.0, duplicates=0.0)


def test_a_scan_with_the_digests_kept_reads_no_unchanged_file_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0020.18]
    root = tmp_path / "root"
    write(root / "a.bin", b"same")
    write(root / "b.bin", b"same")
    kept = Digests()
    first = scan([root], context(tmp_path), digests=kept)
    read: list[Path] = []

    def spy(path: Path, **kwargs: object) -> str:
        read.append(path)
        return ""

    monkeypatch.setattr(hashing, "hash_file", spy)
    again = scan([root], context(tmp_path), digests=kept)
    assert again.duplicates == first.duplicates
    assert read == []


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
