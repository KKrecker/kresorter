"""Single-instance lock on the data directory (decision 0009, addendum).

Two kresorter processes on one data directory would each treat the other's in-flight operation
as interrupted. The lock is an OS advisory lock on ``<data dir>/kresorter.lock``: ``flock`` on
Linux/macOS, ``msvcrt.locking`` on Windows. The kernel drops it when the holder dies, so a crash
never leaves a stale lock. The lock file itself is never deleted (decision 0001).
"""

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from kresorter.storage.lock import (
    FlockBackend,
    InstanceLock,
    LockedError,
    MsvcrtBackend,
    backend_for_platform,
)
from kresorter.storage.transactions import StorageError
from support.host import as_kept

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="flock backend")

HOLDER = """
import sys
from pathlib import Path
from kresorter.storage.lock import InstanceLock

with InstanceLock(Path(sys.argv[1])):
    print("locked", flush=True)
    sys.stdin.readline()
"""


@pytest.fixture
def lock_path(tmp_path: Path) -> Path:
    return tmp_path / "kresorter.lock"


def hold_in_another_process(lock_path: Path) -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "locked"
    return holder


# --- behaviour ---------------------------------------------------------------------------------


def test_lock_creates_a_private_file_and_keeps_it(lock_path: Path) -> None:
    with InstanceLock(lock_path):
        assert stat.S_IMODE(lock_path.stat().st_mode) == as_kept(0o600)
    assert lock_path.is_file()  # released, never deleted


def test_a_loosened_lock_file_is_made_private_again(lock_path: Path) -> None:
    lock_path.touch()
    lock_path.chmod(0o666)
    with InstanceLock(lock_path):
        assert stat.S_IMODE(lock_path.stat().st_mode) == as_kept(0o600)


def test_second_lock_in_the_same_process_is_refused(lock_path: Path) -> None:
    with InstanceLock(lock_path), pytest.raises(LockedError, match="another kresorter"):
        InstanceLock(lock_path).__enter__()


def test_lock_is_free_again_after_release(lock_path: Path) -> None:
    with InstanceLock(lock_path):
        pass
    with InstanceLock(lock_path):
        pass


def test_lock_is_released_when_the_body_raises(lock_path: Path) -> None:
    with pytest.raises(RuntimeError), InstanceLock(lock_path):
        raise RuntimeError("boom")
    with InstanceLock(lock_path):
        pass


@posix_only
def test_lock_held_by_another_process_is_refused(lock_path: Path) -> None:
    holder = hold_in_another_process(lock_path)
    try:
        with pytest.raises(LockedError):
            InstanceLock(lock_path).__enter__()
    finally:
        holder.communicate("\n")
    with InstanceLock(lock_path):
        pass


@posix_only
def test_a_crashed_holder_leaves_no_stale_lock(lock_path: Path) -> None:
    holder = hold_in_another_process(lock_path)
    holder.kill()
    holder.communicate()
    with InstanceLock(lock_path):
        pass


@posix_only
def test_a_link_in_place_of_the_lock_is_refused(lock_path: Path, tmp_path: Path) -> None:
    # [0018.36] Found by the audit: the lock made the link's target private, and held it.
    target = tmp_path / "elsewhere"
    target.write_bytes(b"kept")
    target.chmod(0o644)
    lock_path.symlink_to(target)
    with pytest.raises(OSError, match=re.escape(lock_path.name)), InstanceLock(lock_path):
        pytest.fail("locked through a link")
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert target.read_bytes() == b"kept"


def test_missing_directory_is_an_os_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        InstanceLock(tmp_path / "nope" / "kresorter.lock").__enter__()


def test_locked_error_is_a_storage_error() -> None:
    assert issubclass(LockedError, StorageError)


# --- backends ----------------------------------------------------------------------------------


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_posix_platforms_use_flock(platform: str) -> None:
    assert isinstance(backend_for_platform(platform), FlockBackend)


def test_windows_uses_msvcrt() -> None:
    assert isinstance(backend_for_platform("win32"), MsvcrtBackend)


class FakeMsvcrt:
    """Records ``msvcrt.locking`` calls; refuses the lock when ``busy``."""

    LK_NBLCK = 2
    LK_UNLCK = 0

    def __init__(self, busy: bool = False) -> None:
        self.busy = busy
        self.calls: list[tuple[int, int, int]] = []

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        self.calls.append((fd, mode, nbytes))
        if self.busy and mode == self.LK_NBLCK:
            raise PermissionError(13, "Permission denied")


def test_msvcrt_backend_locks_and_unlocks_one_byte(lock_path: Path) -> None:
    fake = FakeMsvcrt()
    with InstanceLock(lock_path, backend=MsvcrtBackend(module=fake)):
        pass
    assert [(mode, nbytes) for _, mode, nbytes in fake.calls] == [(2, 1), (0, 1)]


def test_msvcrt_backend_reports_a_busy_lock(lock_path: Path) -> None:
    fake = FakeMsvcrt(busy=True)
    backend = MsvcrtBackend(module=fake)
    with pytest.raises(LockedError):
        InstanceLock(lock_path, backend=backend).__enter__()
    assert [mode for _, mode, _ in fake.calls] == [2]


class FakeFcntl:
    """Records ``fcntl.flock`` calls; refuses the lock when ``busy``, as a held one would."""

    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    def __init__(self, busy: bool = False) -> None:
        self.busy = busy
        self.calls: list[tuple[int, int]] = []

    def flock(self, fd: int, operation: int) -> None:
        self.calls.append((fd, operation))
        if self.busy and operation & self.LOCK_EX:
            raise BlockingIOError(11, "Resource temporarily unavailable")


def test_flock_backend_locks_without_waiting_and_unlocks(lock_path: Path) -> None:
    # [0015.20] fcntl is a module given, as msvcrt is: the backend is checked on Windows too
    fake = FakeFcntl()
    with InstanceLock(lock_path, backend=FlockBackend(module=fake)):
        pass
    assert [operation for _, operation in fake.calls] == [2 | 4, 8]


def test_flock_backend_reports_a_busy_lock(lock_path: Path) -> None:
    # [0015.20]
    fake = FakeFcntl(busy=True)
    with pytest.raises(LockedError):
        InstanceLock(lock_path, backend=FlockBackend(module=fake)).__enter__()
    assert [operation for _, operation in fake.calls] == [2 | 4]


@pytest.mark.skipif(sys.platform != "win32", reason="fcntl exists elsewhere")
def test_flock_backend_imports_fcntl_lazily(lock_path: Path) -> None:
    # [0015.20]
    backend = backend_for_platform("linux")  # constructing it imports nothing
    with pytest.raises(ModuleNotFoundError, match="fcntl"):
        InstanceLock(lock_path, backend=backend).__enter__()


@pytest.mark.skipif(sys.platform == "win32", reason="msvcrt exists there")
def test_msvcrt_backend_imports_msvcrt_lazily(lock_path: Path) -> None:
    backend = backend_for_platform("win32")  # constructing it imports nothing
    with pytest.raises(ModuleNotFoundError, match="msvcrt"):
        InstanceLock(lock_path, backend=backend).__enter__()
