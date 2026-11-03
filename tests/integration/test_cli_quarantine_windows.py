"""Live on Windows (decision 0016, item 9; skipped elsewhere): the quarantine commands with the
running system's context, in a temporary profile.

The context is ``default_context`` for a made-up profile under ``tmp_path``: its policy, its
share-mode check, its data directory. One rule leaves its classifier: the runner's temporary
folder is ``AppData\\Local\\Temp``, which ``windows-user-temp`` marks as junk, as the tests of
Linux leave ``posix-temp`` out. ``tmp_path`` is taken resolved: a short name (``RUNNER~1``)
leads elsewhere and is 0017's (item 12).
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from kresorter import environment
from kresorter.core.heuristics import JunkClassifier, default_rules
from kresorter.core.open_files import ShareModeChecker
from kresorter.core.scanner import ScanContext
from support.cli import run
from support.files import write
from support.holder import held_by_a_child
from support.journal import query

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="live Windows quarantine")

MTIME_NS = 1_600_000_000_123_456_700  # NTFS keeps 100 ns


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path.resolve() / "Alice"


@pytest.fixture
def data_dir(home: Path) -> Path:
    return home / "AppData" / "Local" / "kresorter"


@pytest.fixture
def context(home: Path) -> ScanContext:
    profile = {  # the names the policy reads; os.environ ignores the case on Windows
        "SystemDrive": os.environ.get("SYSTEMDRIVE", "C:"),
        "SystemRoot": os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
    }
    made = environment.default_context(env=profile)
    rules = [r for r in default_rules() if r.id != "windows-user-temp"]
    return replace(made, classifier=JunkClassifier(rules, platform="windows"))


@pytest.fixture
def downloads(home: Path) -> Path:
    return home / "Downloads"


def stamped(path: Path) -> Path:
    os.utime(path, ns=(MTIME_NS, MTIME_NS))
    return path


def slots(data_dir: Path) -> list[Path]:
    return [Path(str(v)) for (v,) in query(data_dir, "SELECT vault_path FROM items ORDER BY id")]


def test_live_the_context_is_the_running_systems(context: ScanContext, data_dir: Path) -> None:
    # [0016.9] the share-mode check, the profile's data directory
    assert isinstance(context.open_files, ShareModeChecker)
    assert context.open_files_checked is True
    assert context.policy.app_data_dir == data_dir


def test_live_quarantine_restore_and_purge(
    context: ScanContext, downloads: Path, data_dir: Path
) -> None:
    # [0016.9] safe findings into the vault, back with their mtime_ns, then purged
    first = stamped(write(downloads / "proj" / "__pycache__" / "a.cpython-313.pyc", b"first"))
    second = stamped(write(downloads / "proj" / "__pycache__" / "b.cpython-313.pyc", b"second"))
    notes = write(downloads / "notes.txt", b"kept")
    add = ["quarantine", "add", "--from-analysis", str(downloads), "--level", "safe", "--yes"]

    code, out, err = run(add, context)

    assert (code, err) == (0, ""), out
    assert "Quarantined 2 files, 11 B" in out
    assert not first.exists()
    assert not second.exists()
    assert notes.read_bytes() == b"kept"
    assert sorted(slot.read_bytes() for slot in slots(data_dir)) == [b"first", b"second"]

    code, out, _ = run(["quarantine", "restore", "1", "2"], context)

    assert code == 0, out
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"
    assert first.stat().st_mtime_ns == second.stat().st_mtime_ns == MTIME_NS

    code, out, _ = run(add, context)
    assert code == 0, out
    code, out, _ = run(["quarantine", "purge", "--yes", "3", "4"], context)

    assert code == 0, out
    assert "Permanently deleted 2 files, 11 B" in out
    assert [slot.exists() for slot in slots(data_dir)] == [False, False, False, False]
    assert not first.exists()
    assert notes.read_bytes() == b"kept"


def test_live_a_file_a_child_process_holds_is_refused(
    context: ScanContext, downloads: Path, data_dir: Path
) -> None:
    # [0016.9]
    held = write(downloads / "held.bin", b"held")

    with held_by_a_child(held):
        code, out, _ = run(["quarantine", "add", str(held)], context)

    assert code == 1
    assert f"open_file: {held}" in out
    assert held.read_bytes() == b"held"
    assert query(data_dir, "SELECT COUNT(*) FROM items") == [(0,)]


def test_live_a_file_on_another_drive_is_refused(
    context: ScanContext, home: Path, data_dir: Path
) -> None:
    # [0016.9] the checkout's drive, where the runner has one apart from the temporary folder's
    other = Path(__file__).resolve()
    if other.drive.lower() == home.drive.lower():
        pytest.skip("no second drive: the checkout and the temporary folder share one")

    code, out, _ = run(["quarantine", "add", str(other)], context)

    assert code == 1
    assert f"cross_device: {other}" in out
    assert other.is_file()
    assert query(data_dir, "SELECT COUNT(*) FROM items") == [(0,)]
