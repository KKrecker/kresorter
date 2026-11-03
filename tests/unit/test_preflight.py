"""Preflight: re-validate one candidate right before the quarantine acts (decision 0004, item 5).

Every refusal reason has its own case. Cheap, pure checks run before disk checks, and the
open-file check (a full /proc scan on Linux) runs last.
"""

import os
from pathlib import Path

import pytest

from fakes import BrokenOpenFiles, FakeOpenFiles, make_policy
from kresorter.core.hashing import hash_file
from kresorter.core.models import FileEntry
from kresorter.core.open_files import NoOpenFileCheck
from kresorter.core.policy import BlockReason, PathPolicy
from kresorter.core.preflight import (
    Candidate,
    Cleared,
    Preflight,
    RefusalReason,
    Refused,
    UnreliableCheckerError,
)
from support.files import write

# --- helpers -----------------------------------------------------------------------------------


def scanned(path: Path) -> FileEntry:
    """FileEntry as the scanner would have recorded it now."""
    info = path.lstat()
    return FileEntry(path=path, size=info.st_size, mtime_ns=info.st_mtime_ns)


def refusal(result: Cleared | Refused) -> RefusalReason:
    assert isinstance(result, Refused), result
    return result.reason


@pytest.fixture
def policy(tmp_path: Path) -> PathPolicy:
    return make_policy(tmp_path, tmp_path / "system")


@pytest.fixture
def preflight(policy: PathPolicy) -> Preflight:
    return Preflight(policy, FakeOpenFiles())


# --- construction ------------------------------------------------------------------------------


def test_unreliable_checker_is_refused(policy: PathPolicy) -> None:
    with pytest.raises(UnreliableCheckerError):
        Preflight(policy, NoOpenFileCheck())


def test_twin_without_digest_is_invalid(zone: Path) -> None:
    entry = scanned(write(zone / "a.bin"))
    twin = scanned(write(zone / "b.bin"))
    with pytest.raises(ValueError, match="digest"):
        Candidate(entry=entry, twin=twin)


def test_twin_at_the_same_path_is_invalid(zone: Path) -> None:
    entry = scanned(write(zone / "a.bin"))
    with pytest.raises(ValueError, match="itself"):
        Candidate(entry=entry, twin=entry, digest="00")


# --- happy path --------------------------------------------------------------------------------


def test_unchanged_file_is_cleared_with_its_fresh_stat(preflight: Preflight, zone: Path) -> None:
    entry = scanned(write(zone / "a.bin"))
    result = preflight.check(Candidate(entry=entry))
    assert isinstance(result, Cleared)
    assert result.candidate.entry == entry
    assert result.stat.st_ino == entry.path.lstat().st_ino  # service needs st_dev and mode


def test_unchanged_duplicate_with_intact_twin_is_cleared(preflight: Preflight, zone: Path) -> None:
    entry = scanned(write(zone / "a.bin"))
    twin = scanned(write(zone / "b.bin"))
    candidate = Candidate(entry=entry, twin=twin, digest=hash_file(twin.path))
    assert isinstance(preflight.check(candidate), Cleared)


# --- policy ------------------------------------------------------------------------------------


def test_blacklisted_path_is_refused(preflight: Preflight, tmp_path: Path) -> None:
    entry = scanned(write(tmp_path / "system" / "a.bin"))
    result = preflight.check(Candidate(entry=entry))
    assert refusal(result) is RefusalReason.BLOCKED
    assert isinstance(result, Refused)
    assert result.block_reason is BlockReason.SYSTEM


def test_open_file_is_refused(policy: PathPolicy, zone: Path) -> None:
    entry = scanned(write(zone / "a.bin"))
    result = Preflight(policy, FakeOpenFiles([entry.path])).check(Candidate(entry=entry))
    assert refusal(result) is RefusalReason.OPEN_FILE


def test_failing_checker_counts_as_open(policy: PathPolicy, zone: Path) -> None:
    entry = scanned(write(zone / "a.bin"))
    result = Preflight(policy, BrokenOpenFiles()).check(Candidate(entry=entry))
    assert refusal(result) is RefusalReason.OPEN_FILE


# --- the file itself ---------------------------------------------------------------------------


def test_missing_file_is_refused(preflight: Preflight, zone: Path) -> None:
    entry = scanned(write(zone / "a.bin"))
    entry.path.replace(zone / "moved.bin")
    assert refusal(preflight.check(Candidate(entry=entry))) is RefusalReason.NOT_FOUND


def test_file_replaced_by_symlink_is_refused(preflight: Preflight, zone: Path) -> None:
    entry = scanned(write(zone / "a.bin"))
    entry.path.replace(zone / "real.bin")
    entry.path.symlink_to(zone / "real.bin")
    assert refusal(preflight.check(Candidate(entry=entry))) is RefusalReason.SYMLINK


def test_file_replaced_by_directory_is_refused(preflight: Preflight, zone: Path) -> None:
    entry = scanned(write(zone / "a.bin"))
    entry.path.replace(zone / "moved.bin")
    entry.path.mkdir()
    assert refusal(preflight.check(Candidate(entry=entry))) is RefusalReason.NOT_REGULAR


def test_file_replaced_by_fifo_is_refused(preflight: Preflight, zone: Path) -> None:
    entry = scanned(write(zone / "a.bin"))
    entry.path.replace(zone / "moved.bin")
    os.mkfifo(entry.path)
    assert refusal(preflight.check(Candidate(entry=entry))) is RefusalReason.NOT_REGULAR


def test_size_change_is_refused(preflight: Preflight, zone: Path) -> None:
    entry = scanned(write(zone / "a.bin"))
    write(entry.path, b"grown payload")
    os.utime(entry.path, ns=(entry.mtime_ns, entry.mtime_ns))  # same mtime, other size
    assert refusal(preflight.check(Candidate(entry=entry))) is RefusalReason.CHANGED


def test_mtime_change_is_refused(preflight: Preflight, zone: Path) -> None:
    entry = scanned(write(zone / "a.bin"))
    os.utime(entry.path, ns=(entry.mtime_ns, entry.mtime_ns + 1))  # one nanosecond is enough
    assert refusal(preflight.check(Candidate(entry=entry))) is RefusalReason.CHANGED


def test_unreadable_path_is_refused_with_detail(preflight: Preflight, zone: Path) -> None:
    # Parent directory replaced by a regular file: lstat fails with ENOTDIR.
    entry = scanned(write(zone / "dir" / "a.bin"))
    (zone / "dir").replace(zone / "old-dir")
    write(zone / "dir")
    result = preflight.check(Candidate(entry=entry))
    assert refusal(result) is RefusalReason.UNREADABLE
    assert isinstance(result, Refused)
    assert result.detail


# --- parent swapped for a link -----------------------------------------------------------------


def test_parent_swapped_for_symlink_is_refused(preflight: Preflight, zone: Path) -> None:
    # The decoy has the same name, size and mtime: only the parent check can catch it.
    entry = scanned(write(zone / "dir" / "a.bin"))
    decoy = write(zone / "elsewhere" / "a.bin")
    os.utime(decoy, ns=(entry.mtime_ns, entry.mtime_ns))
    (zone / "dir").replace(zone / "old-dir")
    (zone / "dir").symlink_to(zone / "elsewhere")
    assert refusal(preflight.check(Candidate(entry=entry))) is RefusalReason.PARENT_SWAPPED


def test_grandparent_swapped_for_symlink_is_refused(preflight: Preflight, zone: Path) -> None:
    entry = scanned(write(zone / "top" / "dir" / "a.bin"))
    decoy = write(zone / "elsewhere" / "dir" / "a.bin")
    os.utime(decoy, ns=(entry.mtime_ns, entry.mtime_ns))
    (zone / "top").replace(zone / "old-top")
    (zone / "top").symlink_to(zone / "elsewhere")
    assert refusal(preflight.check(Candidate(entry=entry))) is RefusalReason.PARENT_SWAPPED


# --- duplicate twin ----------------------------------------------------------------------------


@pytest.fixture
def pair(zone: Path) -> tuple[FileEntry, FileEntry, str]:
    entry = scanned(write(zone / "a.bin"))
    twin = scanned(write(zone / "b.bin"))
    return entry, twin, hash_file(twin.path)


def test_missing_twin_is_refused(
    preflight: Preflight, pair: tuple[FileEntry, FileEntry, str]
) -> None:
    entry, twin, digest = pair
    twin.path.replace(twin.path.with_name("gone.bin"))
    result = preflight.check(Candidate(entry=entry, twin=twin, digest=digest))
    assert refusal(result) is RefusalReason.TWIN_MISSING


def test_twin_with_new_mtime_is_refused(
    preflight: Preflight, pair: tuple[FileEntry, FileEntry, str]
) -> None:
    entry, twin, digest = pair
    os.utime(twin.path, ns=(twin.mtime_ns, twin.mtime_ns + 1))
    result = preflight.check(Candidate(entry=entry, twin=twin, digest=digest))
    assert refusal(result) is RefusalReason.TWIN_CHANGED


def test_twin_with_same_stat_but_new_content_is_refused(
    preflight: Preflight, pair: tuple[FileEntry, FileEntry, str]
) -> None:
    # Same size and mtime, different bytes: only the digest catches it.
    entry, twin, digest = pair
    write(twin.path, b"PAYLOAD")
    os.utime(twin.path, ns=(twin.mtime_ns, twin.mtime_ns))
    result = preflight.check(Candidate(entry=entry, twin=twin, digest=digest))
    assert refusal(result) is RefusalReason.TWIN_CHANGED


def test_twin_replaced_by_symlink_is_refused(
    preflight: Preflight, pair: tuple[FileEntry, FileEntry, str]
) -> None:
    # A link back to the candidate would leave no real copy after the move.
    entry, twin, digest = pair
    twin.path.replace(twin.path.with_name("old-b.bin"))
    twin.path.symlink_to(entry.path)
    result = preflight.check(Candidate(entry=entry, twin=twin, digest=digest))
    assert refusal(result) is RefusalReason.TWIN_CHANGED


def test_twin_that_is_a_hard_link_of_the_candidate_is_refused(
    preflight: Preflight, zone: Path
) -> None:
    # Same inode: nothing would be freed, and "the copy that stays" is the same file.
    entry = scanned(write(zone / "a.bin"))
    (zone / "b.bin").hardlink_to(entry.path)
    twin = scanned(zone / "b.bin")
    candidate = Candidate(entry=entry, twin=twin, digest=hash_file(twin.path))
    assert refusal(preflight.check(candidate)) is RefusalReason.TWIN_SAME_FILE


# --- order: first failing check wins, cheap before expensive -----------------------------------


def test_policy_is_checked_before_the_disk(tmp_path: Path) -> None:
    # Blacklisted and missing: the pure check answers without touching the disk.
    open_files = FakeOpenFiles()
    preflight = Preflight(make_policy(tmp_path, tmp_path / "system"), open_files)
    entry = FileEntry(path=tmp_path / "system" / "missing.bin", size=1, mtime_ns=1)
    assert refusal(preflight.check(Candidate(entry=entry))) is RefusalReason.BLOCKED
    assert open_files.calls == []


def test_open_file_check_runs_last(policy: PathPolicy, zone: Path) -> None:
    open_files = FakeOpenFiles()
    entry = scanned(write(zone / "a.bin"))
    os.utime(entry.path, ns=(entry.mtime_ns, entry.mtime_ns + 1))
    result = Preflight(policy, open_files).check(Candidate(entry=entry))
    assert refusal(result) is RefusalReason.CHANGED
    assert open_files.calls == []


def test_every_reason_has_a_case() -> None:
    # Guard: a new RefusalReason must come with its own test above.
    assert {r.value for r in RefusalReason} == {
        "blocked",
        "open_file",
        "not_found",
        "unreadable",
        "symlink",
        "not_regular",
        "changed",
        "parent_swapped",
        "twin_missing",
        "twin_changed",
        "twin_same_file",
        "cross_device",  # checked by the service: tests/unit/test_quarantine_service.py
        "conflict",  # a taken destination, checked by organize: tests/unit/test_organize_mover.py
        "duplicate_candidate",  # checked by the service as well
    }
