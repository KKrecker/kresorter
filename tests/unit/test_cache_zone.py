"""The programs' caches: a zone of the window on Windows, read for junk only (decision 0020,
item 15). Its folders are where the rules find caches under AppData\\Local and LocalLow; its
files are not compared as duplicates and not rated by size or age."""

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

import pytest

from fakes import FakeOpenFiles, make_policy
from kresorter.analysis.report import analyze
from kresorter.analysis.run import analyze_paths
from kresorter.analysis.size_age import DAY_NS, Thresholds
from kresorter.core.heuristics import JunkCategory, JunkClassifier, default_rules, load_rules
from kresorter.core.models import FileEntry
from kresorter.core.policy import CACHES, PathPolicy
from kresorter.core.scanner import ScanContext, ScanReport, scan
from kresorter.organize.synced import NoSyncedFolders
from support.files import write
from support.host import host_classifier

HOME = PureWindowsPath(r"C:\Users\Alice")
WIN = PathPolicy.for_windows({"SystemDrive": "C:", "USERPROFILE": str(HOME)})

# A folder of the zone, from the home, and a file a rule finds there.
FOLDERS = {
    r"AppData\Local\Google\Chrome\User Data": r"Default\Cache\Cache_Data\f_1",
    r"AppData\Local\Microsoft\Edge\User Data": r"Default\Code Cache\js\x",
    r"AppData\Local\BraveSoftware\Brave-Browser\User Data": r"Default\GPUCache\data_0",
    r"AppData\Local\Vivaldi\User Data": r"Default\DawnCache\data_0",
    r"AppData\Local\Yandex\YandexBrowser\User Data": r"Default\Cache\Cache_Data\f_2",
    r"AppData\Local\Chromium\User Data": r"GrShaderCache\data_0",
    r"AppData\Local\Opera Software": r"Opera Stable\Cache\Cache_Data\f_1",
    r"AppData\Local\Mozilla\Firefox\Profiles": r"x.default-release\cache2\entries\A1",
    r"AppData\Local\Microsoft\Windows\INetCache": r"IE\x\page.htm",
    r"AppData\Local\Microsoft\Windows\Explorer": "thumbcache_256.db",
    r"AppData\Local\Microsoft\Windows\WER\ReportArchive": r"AppCrash_x\Report.wer",
    r"AppData\Local\Microsoft\Windows\WER\ReportQueue": r"AppHang_x\Report.wer",
    r"AppData\Local\CrashDumps": "app.exe.1234.dmp",
    r"AppData\Local\NVIDIA\DXCache": "1a2b.nvph",
    r"AppData\Local\NVIDIA\GLCache": r"x\y.bin",
    r"AppData\LocalLow\NVIDIA\PerDriverVersion": r"DXCache\x.nvph",
    r"AppData\Local\AMD\DxCache": "x.parc",
    r"AppData\Local\AMD\DxcCache": "x.parc",
    r"AppData\Local\AMD\GLCache": "x.bin",
    r"AppData\Local\AMD\VkCache": "x.parc",
    r"AppData\LocalLow\Intel\ShaderCache": "x.bin",
    r"AppData\Local\D3DSCache": r"x\y.idx",
}


def test_on_windows_the_programs_caches_are_a_zone_of_their_own() -> None:
    # [0020.15] by the name caches, after the safe zones
    assert WIN.cache_zone() == tuple(HOME / folder for folder in FOLDERS)
    assert WIN.zone_names() == (".cache", "Downloads", CACHES)
    assert CACHES == "caches"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_elsewhere_there_is_none(platform: Literal["linux", "darwin"]) -> None:
    # [0020.15] on Linux ~/.cache is a safe zone already; on macOS no rule is under one folder
    policy = PathPolicy.for_posix(home=PurePosixPath("/home/alice"), platform=platform)
    assert policy.cache_zone() == ()
    assert policy.zone_names() == (".cache", "Downloads")


@pytest.mark.parametrize(("folder", "example"), FOLDERS.items())
def test_each_folder_of_the_zone_holds_a_rule_s_cache_and_is_allowed(
    folder: str, example: str
) -> None:
    # [0020.15] its files read for junk: a rule finds some, the policy blocks none of them
    path = HOME / folder / example
    match = JunkClassifier(default_rules(), platform="windows").classify(path)
    assert match is not None
    assert match.category is not JunkCategory.TEMP
    assert WIN.check_path(HOME / folder).allowed
    assert WIN.check_path(path).allowed


def test_each_rule_under_appdata_but_temp_has_its_folders_in_the_zone() -> None:
    # [0020.15] the temporary files are scanned only when chosen (decision 0002)
    zone = WIN.cache_zone()
    for rule in default_rules():
        if "windows" not in rule.platforms or rule.category is JunkCategory.TEMP:
            continue
        for pattern in rule.dirs:
            if pattern.segments[:2] in (("AppData", "Local"), ("AppData", "LocalLow")):
                folder = HOME.joinpath(*pattern.segments)
                assert any(folder.is_relative_to(z) for z in zone), (rule.id, folder)


# --- a scan of the zone ---------------------------------------------------------------------------

RULES = """
[[rule]]
id = "tmp-ext"
category = "temp"
description = "Temporary file"
files = ["*.tmp"]
"""
CLASSIFIER = host_classifier(load_rules(RULES))
NOW = 1_700_000_000_000_000_000
OLD = NOW - 400 * DAY_NS
THRESHOLDS = Thresholds(large_bytes=1000, old_after_days=365)


def context(tmp_path: Path, *zones: Path) -> ScanContext:
    return ScanContext(
        policy=make_policy(tmp_path, default_roots=zones),
        open_files=FakeOpenFiles(),
        classifier=CLASSIFIER,
        open_files_checked=True,
        platform="linux",
        synced=NoSyncedFolders(),
    )


def entries(report: ScanReport) -> list[Path]:
    return [entry.path for entry in report.compared]


def test_a_scan_reads_the_zone_for_junk_only(tmp_path: Path) -> None:
    # [0020.15] its junk found, its files compared as duplicates with none
    root, caches = tmp_path / "root", tmp_path / "caches"
    photo = write(root / "photo.jpg", b"same")
    copy = write(caches / "copy.jpg", b"same")
    junk = write(caches / "x.tmp", b"junk")

    report = scan([root], context(tmp_path), junk_only=[caches])

    assert (report.roots, report.junk_only_roots) == ((root,), (caches,))
    assert report.files_scanned == 3
    assert [finding.entry.path for finding in report.junk] == [junk]
    assert report.duplicates == ()
    assert report.junk_only == frozenset({copy, junk})
    assert entries(report) == [photo]


def test_a_folder_of_the_zone_in_a_folder_scanned_is_read_as_that_one(tmp_path: Path) -> None:
    # [0020.15] what the user chose is read whole
    root = tmp_path / "root"
    photo = write(root / "photo.jpg", b"same")
    copy = write(root / "caches" / "copy.jpg", b"same")

    report = scan([root], context(tmp_path), junk_only=[root / "caches"])

    assert report.junk_only == frozenset()
    assert entries(report) == [copy, photo]
    assert [group.paths for group in report.duplicates] == [(copy, photo)]


def test_a_folder_scanned_in_the_zone_is_read_whole_and_once(tmp_path: Path) -> None:
    # [0020.15] and the rest of the zone for junk only
    caches = tmp_path / "caches"
    mine = write(caches / "mine" / "photo.jpg", b"same")
    copy = write(caches / "copy.jpg", b"same")

    report = scan([caches / "mine"], context(tmp_path), junk_only=[caches])

    assert report.files_scanned == 2
    assert report.junk_only == frozenset({copy})
    assert entries(report) == [mine]


def test_a_file_read_for_junk_only_is_not_rated_by_size_or_age(tmp_path: Path) -> None:
    # [0020.15] nor compared: only its junk is a finding
    root, caches = tmp_path / "root", tmp_path / "caches"
    mine = write(root / "disk.img", b"x" * 1000)
    for path in (mine, write(caches / "disk.img", b"x" * 1000), write(caches / "old.bin", b"o")):
        os.utime(path, ns=(OLD, OLD))
    junk = write(caches / "x.tmp", b"junk")

    analysis = analyze(
        scan([root], context(tmp_path), junk_only=[caches]),
        classifier=CLASSIFIER,
        safe_zones=[],
        now_ns=NOW,
        thresholds=THRESHOLDS,
    )

    assert sorted(finding.entry.path for finding in analysis.findings) == sorted([mine, junk])
    assert analysis.duplicates == ()


def test_the_zone_is_read_where_its_folders_are_when_the_scan_starts(tmp_path: Path) -> None:
    # [0020.15] a folder a program has not made is not a path skipped
    zone, caches = tmp_path / "zone", tmp_path / "caches"
    zone.mkdir()
    junk = write(caches / "x.tmp", b"junk")
    missing = tmp_path / "missing"
    write(tmp_path / "file", b"not a folder")

    scanned, analysis = analyze_paths(
        [], context(tmp_path, zone), THRESHOLDS, junk_only=[missing, caches, tmp_path / "file"]
    )

    assert scanned.junk_only_roots == (caches,)
    assert scanned.skipped == ()
    assert [finding.entry.path for finding in analysis.findings] == [junk]


def test_without_the_zone_every_file_is_compared(tmp_path: Path) -> None:
    root = tmp_path / "root"
    photo = write(root / "photo.jpg", b"same")
    report = scan([root], context(tmp_path))
    assert (report.junk_only_roots, report.junk_only) == ((), frozenset())
    assert report.compared == report.entries == (FileEntry(photo, 4, photo.stat().st_mtime_ns),)
