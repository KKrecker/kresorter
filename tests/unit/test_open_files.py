"""Open-file check: protocol with ``reliable`` and the Linux ``/proc/*/fd`` backend.

Most cases run against a fake ``/proc`` tree in ``tmp_path`` (symlinks, like the real one), so
they are deterministic; one case uses the live ``/proc`` of this test process on Linux only.
"""

import os
import sys
from pathlib import Path

import pytest

from safeclean.core.open_files import (
    NoOpenFileCheck,
    OpenFileChecker,
    OpenFileCheckError,
    ProcFdChecker,
    checker_for_platform,
)

# --- fake /proc helpers ------------------------------------------------------------------------


def add_fd(proc: Path, pid: str, fd: int, target: str | Path) -> None:
    fd_dir = proc / pid / "fd"
    fd_dir.mkdir(parents=True, exist_ok=True)
    (fd_dir / str(fd)).symlink_to(target)


@pytest.fixture
def proc(tmp_path: Path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    return root


@pytest.fixture
def target(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "file.bin"
    path.parent.mkdir()
    path.write_bytes(b"x")
    return path


# --- protocol: reliable ------------------------------------------------------------------------


def test_placeholder_is_not_reliable() -> None:
    assert NoOpenFileCheck().reliable is False


def test_proc_backend_is_reliable(proc: Path) -> None:
    assert ProcFdChecker(proc_root=proc).reliable is True


def test_both_satisfy_the_protocol(proc: Path) -> None:
    checkers: list[OpenFileChecker] = [NoOpenFileCheck(), ProcFdChecker(proc_root=proc)]
    assert all(isinstance(c.reliable, bool) for c in checkers)


# --- /proc backend on a fake tree --------------------------------------------------------------


def test_file_held_by_a_process_is_open(proc: Path, target: Path) -> None:
    add_fd(proc, "123", 3, target)
    assert ProcFdChecker(proc_root=proc).is_open(target) is True


def test_file_held_by_nobody_is_not_open(proc: Path, target: Path, tmp_path: Path) -> None:
    other = tmp_path / "data" / "other.bin"
    other.write_bytes(b"y")
    add_fd(proc, "123", 3, other)
    assert ProcFdChecker(proc_root=proc).is_open(target) is False


def test_hard_link_to_an_open_file_is_open(proc: Path, target: Path) -> None:
    # Identity is (st_dev, st_ino), not the path string: a hard link is the same file.
    alias = target.with_name("alias.bin")
    alias.hardlink_to(target)
    add_fd(proc, "123", 3, alias)
    assert ProcFdChecker(proc_root=proc).is_open(target) is True


def test_non_pid_entries_are_ignored(proc: Path, target: Path) -> None:
    # /proc/self, /proc/sys, ... are not processes; "self" would otherwise double-count.
    add_fd(proc, "self", 3, target)
    (proc / "sys").mkdir()
    assert ProcFdChecker(proc_root=proc).is_open(target) is False


def test_pseudo_fds_are_ignored(proc: Path, target: Path) -> None:
    # Real /proc shows sockets, pipes and anon inodes as dangling links like "socket:[42]".
    add_fd(proc, "123", 0, "socket:[42]")
    add_fd(proc, "123", 1, "pipe:[43]")
    add_fd(proc, "123", 2, "anon_inode:[eventfd]")
    assert ProcFdChecker(proc_root=proc).is_open(target) is False


def test_process_that_exited_mid_scan_is_skipped(proc: Path, target: Path) -> None:
    (proc / "123").mkdir()  # pid dir present, fd dir already gone
    add_fd(proc, "456", 3, target)
    assert ProcFdChecker(proc_root=proc).is_open(target) is True


def test_unreadable_process_is_skipped(
    proc: Path, target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Other users' processes are not inspectable without privileges (documented limitation).
    add_fd(proc, "1", 3, target)
    add_fd(proc, "123", 3, target.with_name("other"))
    real_scandir = os.scandir

    def scandir(path: str | Path) -> object:
        if Path(path) == proc / "1" / "fd":
            raise PermissionError(13, "Permission denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    assert ProcFdChecker(proc_root=proc).is_open(target) is False


def test_missing_proc_fails_closed(tmp_path: Path, target: Path) -> None:
    checker = ProcFdChecker(proc_root=tmp_path / "no-proc")
    with pytest.raises(OpenFileCheckError, match="proc"):
        checker.is_open(target)


def test_missing_target_fails_closed(proc: Path, tmp_path: Path) -> None:
    with pytest.raises(OpenFileCheckError, match=r"missing\.bin"):
        ProcFdChecker(proc_root=proc).is_open(tmp_path / "missing.bin")


def test_check_error_is_an_oserror() -> None:
    # PathPolicy.check_file already treats any OSError from the checker as "open" (fail closed).
    assert issubclass(OpenFileCheckError, OSError)


# --- live /proc --------------------------------------------------------------------------------


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc backend")
def test_live_proc_sees_a_file_this_process_holds(tmp_path: Path) -> None:
    path = tmp_path / "held.bin"
    path.write_bytes(b"x")
    checker = ProcFdChecker()
    with path.open("rb"):
        assert checker.is_open(path) is True
    assert checker.is_open(path) is False


# --- platform selection ------------------------------------------------------------------------


def test_linux_gets_the_proc_backend() -> None:
    checker = checker_for_platform("linux")
    assert isinstance(checker, ProcFdChecker)
    assert checker.reliable is True


@pytest.mark.parametrize("platform", ["win32", "darwin", "freebsd14"])
def test_other_platforms_get_an_unreliable_checker(platform: str) -> None:
    # Quarantine refuses to start without reliable=True: a polite refusal (decision 0004, item 9).
    assert checker_for_platform(platform).reliable is False
