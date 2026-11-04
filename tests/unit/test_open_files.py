"""Open-file check: protocol with ``reliable`` and the Linux ``/proc/*/fd`` backend.

Most cases run against a fake ``/proc`` tree in ``tmp_path`` (symlinks, like the real one), so
they are deterministic; one case uses the live ``/proc`` of this test process on Linux only.
"""

import os
import sys
from pathlib import Path

import pytest

from kresorter.core.open_files import (
    NoOpenFileCheck,
    OpenFileChecker,
    OpenFileCheckError,
    ProcFdChecker,
    checker_for_platform,
    for_scan,
)
from kresorter.core.open_files.windows import ShareModeChecker
from support.kernel import FakeCtypes, FakeKernel

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


def test_placeholder_reports_nothing_as_open(tmp_path: Path) -> None:
    # Which is exactly why it is unreliable: a scan may use it only with disclosure.
    assert NoOpenFileCheck().is_open(tmp_path) is False


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


# --- one look per scan (decision 0018, item 11) ------------------------------------------------


def test_a_snapshot_sees_what_every_process_held_when_it_was_taken(
    proc: Path, target: Path, tmp_path: Path
) -> None:
    # [0018.11] Listed once: a file is open when its (st_dev, st_ino) is among them, through
    # every hard link; pseudo fds and a process gone meanwhile are no answer.
    link = tmp_path / "data" / "link.bin"
    os.link(target, link)
    other = tmp_path / "data" / "other.bin"
    other.write_bytes(b"y")
    (proc / "99").mkdir()  # its fd directory already gone
    add_fd(proc, "123", 0, "socket:[42]")
    add_fd(proc, "123", 3, target)
    (proc / "self").mkdir()  # not a process
    snapshot = ProcFdChecker(proc_root=proc).snapshot()
    assert snapshot.reliable is True
    assert [snapshot.is_open(p) for p in (target, link, other)] == [True, True, False]


def test_a_file_opened_after_the_snapshot_is_not_seen_by_it_but_by_the_checker(
    proc: Path, target: Path
) -> None:
    # [0018.11] The scan's look is not asked again; preflight asks /proc afresh (0004 item 5).
    checker = ProcFdChecker(proc_root=proc)
    snapshot = checker.snapshot()
    add_fd(proc, "123", 3, target)
    assert snapshot.is_open(target) is False
    assert checker.is_open(target) is True


def test_a_snapshot_lists_proc_once(
    proc: Path, target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0018.11] However many files it is asked about.
    add_fd(proc, "123", 3, target)
    listed: list[Path] = []
    real_scandir = os.scandir

    def scandir(path: str | Path) -> object:
        listed.append(Path(path))
        return real_scandir(path)

    snapshot = ProcFdChecker(proc_root=proc).snapshot()
    monkeypatch.setattr(os, "scandir", scandir)
    assert [snapshot.is_open(target) for _ in range(3)] == [True, True, True]
    assert listed == []


def test_a_proc_that_cannot_be_listed_makes_every_file_open(tmp_path: Path, target: Path) -> None:
    # [0018.11] Fail closed: an error, which the policy takes for "open".
    snapshot = ProcFdChecker(proc_root=tmp_path / "no-proc").snapshot()
    with pytest.raises(OpenFileCheckError, match="no-proc"):
        snapshot.is_open(target)


def test_a_snapshot_cannot_check_a_missing_file(proc: Path, tmp_path: Path) -> None:
    with pytest.raises(OpenFileCheckError, match=r"missing\.bin"):
        ProcFdChecker(proc_root=proc).snapshot().is_open(tmp_path / "missing.bin")


def test_a_scan_asks_the_snapshot_of_proc_and_any_other_checker_itself(
    proc: Path, target: Path
) -> None:
    # [0018.11] Only the /proc backend lists every process; the others answer per file.
    add_fd(proc, "123", 3, target)
    checker = ProcFdChecker(proc_root=proc)
    scanned = for_scan(checker)
    assert scanned is not checker
    assert scanned.is_open(target) is True
    others: list[OpenFileChecker] = [NoOpenFileCheck(), ShareModeChecker(FakeKernel())]
    assert [for_scan(other) for other in others] == others


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


@pytest.mark.parametrize("platform", ["windows", "win32"])
def test_windows_gets_the_share_mode_check(kernel32: FakeCtypes, platform: str) -> None:
    # [0016.5] by the name a scan context is made for, or by sys.platform's; kernel32 loaded
    checker = checker_for_platform(platform)
    assert isinstance(checker, ShareModeChecker)
    assert checker.reliable is True
    assert kernel32.loaded == [("kernel32", True)]


@pytest.mark.parametrize("platform", ["darwin", "freebsd14", "cygwin"])
def test_other_platforms_get_an_unreliable_checker(platform: str) -> None:
    # [0016.5] Quarantine refuses to start without reliable=True: a polite refusal (decision
    # 0004, item 9). macOS and every system other than Linux and Windows.
    assert isinstance(checker_for_platform(platform), NoOpenFileCheck)
