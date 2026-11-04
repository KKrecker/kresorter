"""Linux open-file backend: scans ``/proc/<pid>/fd`` for the file's (st_dev, st_ino).

A scan lists every process's open files once, at its start (``snapshot``, decision 0018, item
11); preflight asks ``/proc`` afresh for each file right before it acts (``is_open``).

Limitation (decision 0005): processes whose ``fd`` directory is not readable (other users'
processes without privileges) are skipped, so a file held only by such a process is not seen.
"""

import os
from collections.abc import Iterator
from pathlib import Path, PurePath

from kresorter.core.open_files.base import OpenFileCheckError

_SKIPPED = (FileNotFoundError, ProcessLookupError, PermissionError)

Key = tuple[int, int]  # (st_dev, st_ino): the file itself, through every hard link


class ProcFdChecker:
    def __init__(self, proc_root: Path = Path("/proc")) -> None:
        self._proc_root = proc_root

    @property
    def reliable(self) -> bool:
        return True

    def is_open(self, path: PurePath) -> bool:
        key = _key(path)
        return any(any(held == key for held in _held(fd_dir)) for fd_dir in self._fd_dirs())

    def snapshot(self) -> "ProcSnapshot":
        """Every process's open files as they are now, listed once. A ``/proc`` that cannot be
        listed makes every file open (fail closed)."""
        try:
            fd_dirs = self._fd_dirs()
        except OpenFileCheckError as error:
            return ProcSnapshot(None, str(error))
        return ProcSnapshot(frozenset(key for fd_dir in fd_dirs for key in _held(fd_dir)), "")

    def _fd_dirs(self) -> list[Path]:
        try:
            listing = os.scandir(self._proc_root)
        except OSError as error:
            raise OpenFileCheckError(f"cannot list {self._proc_root}: {error}") from error
        with listing:
            return [Path(e.path) / "fd" for e in listing if e.name.isascii() and e.name.isdigit()]


class ProcSnapshot:
    """The open files a scan was given: ``held`` the keys listed at its start, None when
    ``/proc`` could not be listed (``error``), every file open then."""

    def __init__(self, held: frozenset[Key] | None, error: str) -> None:
        self._held = held
        self._error = error

    @property
    def reliable(self) -> bool:
        return True

    def is_open(self, path: PurePath) -> bool:
        if self._held is None:
            raise OpenFileCheckError(self._error)
        return _key(path) in self._held


def _key(path: PurePath) -> Key:
    try:
        info = Path(path).lstat()
    except OSError as error:
        raise OpenFileCheckError(f"cannot stat {path}: {error}") from error
    return (info.st_dev, info.st_ino)


def _held(fd_dir: Path) -> Iterator[Key]:
    """The files the fds in ``fd_dir`` point at. Gone or unreadable processes: none."""
    try:
        with os.scandir(fd_dir) as fds:
            for fd in fds:
                try:
                    info = fd.stat()  # follows the link to the open file itself
                except _SKIPPED:
                    continue  # fd closed meanwhile, or a pseudo fd (socket:[n], pipe:[n], ...)
                yield (info.st_dev, info.st_ino)
    except _SKIPPED:
        return  # process exited, or not ours to inspect (decision 0005)
