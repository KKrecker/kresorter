"""Open-file check: protocol, placeholder and per-OS backends."""

import sys

from kresorter.core.open_files.base import NoOpenFileCheck, OpenFileChecker, OpenFileCheckError
from kresorter.core.open_files.linux import ProcFdChecker, ProcSnapshot
from kresorter.core.open_files.windows import ShareModeChecker

__all__ = [
    "NoOpenFileCheck",
    "OpenFileCheckError",
    "OpenFileChecker",
    "ProcFdChecker",
    "ProcSnapshot",
    "ShareModeChecker",
    "checker_for_platform",
    "for_scan",
]

_WINDOWS = ("windows", "win32")  # the system a scan context is made for, and sys.platform


def checker_for_platform(platform: str = sys.platform) -> OpenFileChecker:
    """Linux gets the ``/proc`` backend, Windows the share-mode one (decision 0016, item 5);
    other OSes an unreliable placeholder (polite refusal)."""
    if platform.startswith("linux"):
        return ProcFdChecker()
    if platform in _WINDOWS:
        return ShareModeChecker()
    return NoOpenFileCheck()


def for_scan(checker: OpenFileChecker) -> OpenFileChecker:
    """What a scan asks: on Linux every process's open files listed once, at its start (decision
    0018, item 11); any other checker answers per file itself."""
    return checker.snapshot() if isinstance(checker, ProcFdChecker) else checker
