"""Linux open-file backend: scans ``/proc/<pid>/fd`` for the file's (st_dev, st_ino).

Limitation (decision 0005): processes whose ``fd`` directory is not readable (other users'
processes without privileges) are skipped, so a file held only by such a process is not seen.
"""

import os
from pathlib import Path, PurePath

from kresorter.core.open_files.base import OpenFileCheckError

_SKIPPED = (FileNotFoundError, ProcessLookupError, PermissionError)


class ProcFdChecker:
    def __init__(self, proc_root: Path = Path("/proc")) -> None:
        self._proc_root = proc_root

    @property
    def reliable(self) -> bool:
        return True

    def is_open(self, path: PurePath) -> bool:
        try:
            info = Path(path).lstat()
        except OSError as error:
            raise OpenFileCheckError(f"cannot stat {path}: {error}") from error
        key = (info.st_dev, info.st_ino)
        try:
            listing = os.scandir(self._proc_root)
        except OSError as error:
            raise OpenFileCheckError(f"cannot list {self._proc_root}: {error}") from error
        with listing:
            pids = [Path(e.path) for e in listing if e.name.isascii() and e.name.isdigit()]
        return any(_holds(pid_dir / "fd", key) for pid_dir in pids)


def _holds(fd_dir: Path, key: tuple[int, int]) -> bool:
    """True if any fd in ``fd_dir`` points at ``key``. Gone or unreadable processes: False."""
    try:
        with os.scandir(fd_dir) as fds:
            for fd in fds:
                try:
                    info = fd.stat()  # follows the link to the open file itself
                except _SKIPPED:
                    continue  # fd closed meanwhile, or a pseudo fd (socket:[n], pipe:[n], ...)
                if (info.st_dev, info.st_ino) == key:
                    return True
    except _SKIPPED:
        return False  # process exited, or not ours to inspect (decision 0005)
    return False
