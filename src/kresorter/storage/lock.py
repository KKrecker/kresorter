"""Single-instance lock on the data directory (decision 0009, addendum).

An OS advisory lock on one file: ``flock`` on Linux/macOS, ``msvcrt.locking`` on Windows. It is
tied to the open file, so the kernel releases it when the holder exits or crashes: no stale
locks, no pid files. The lock file is created 0600 and never deleted (decision 0001).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import TracebackType
from typing import Protocol, cast

from kresorter.storage.transactions import StorageError

PRIVATE_FILE = 0o600


class LockedError(StorageError):
    """Another kresorter process holds the data directory."""


class LockBackend(Protocol):
    def try_lock(self, fd: int) -> bool:
        """Take the lock without waiting; False if someone else holds it."""
        ...

    def unlock(self, fd: int) -> None: ...


class _Fcntl(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, fd: int, operation: int, /) -> None: ...


class FlockBackend:
    """Locks the whole file; ``fcntl`` is imported only when used, as ``msvcrt`` is."""

    def __init__(self, module: _Fcntl | None = None) -> None:
        self._module = module

    def _fcntl(self) -> _Fcntl:
        if self._module is None:
            self._module = cast("_Fcntl", importlib.import_module("fcntl"))
        return self._module

    def try_lock(self, fd: int) -> bool:
        fcntl = self._fcntl()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def unlock(self, fd: int) -> None:
        fcntl = self._fcntl()
        fcntl.flock(fd, fcntl.LOCK_UN)


class _Msvcrt(Protocol):
    LK_NBLCK: int
    LK_UNLCK: int

    def locking(self, fd: int, mode: int, nbytes: int, /) -> None: ...


class MsvcrtBackend:
    """Locks the first byte of the lock file; ``msvcrt`` is imported only when used."""

    def __init__(self, module: _Msvcrt | None = None) -> None:
        self._module = module

    def _msvcrt(self) -> _Msvcrt:
        if self._module is None:
            self._module = cast("_Msvcrt", importlib.import_module("msvcrt"))
        return self._module

    def try_lock(self, fd: int) -> bool:
        msvcrt = self._msvcrt()
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def unlock(self, fd: int) -> None:
        msvcrt = self._msvcrt()
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def backend_for_platform(platform: str = sys.platform) -> LockBackend:
    return MsvcrtBackend() if platform == "win32" else FlockBackend()


class InstanceLock:
    def __init__(self, path: Path, backend: LockBackend | None = None) -> None:
        self.path = path
        self._backend = backend or backend_for_platform()
        self._fd = -1

    def __enter__(self) -> InstanceLock:
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, PRIVATE_FILE)
        self.path.chmod(PRIVATE_FILE)  # also when it existed with looser permissions
        if not self._backend.try_lock(fd):
            os.close(fd)
            raise LockedError(f"another kresorter is using {self.path.parent}; try again later")
        self._fd = fd
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._backend.unlock(self._fd)
        os.close(self._fd)
        self._fd = -1
