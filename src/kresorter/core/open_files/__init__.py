"""Open-file check: protocol, placeholder and per-OS backends."""

import sys

from kresorter.core.open_files.base import NoOpenFileCheck, OpenFileChecker, OpenFileCheckError
from kresorter.core.open_files.linux import ProcFdChecker

__all__ = [
    "NoOpenFileCheck",
    "OpenFileCheckError",
    "OpenFileChecker",
    "ProcFdChecker",
    "checker_for_platform",
]


def checker_for_platform(platform: str = sys.platform) -> OpenFileChecker:
    """Linux gets the ``/proc`` backend; other OSes an unreliable placeholder (polite refusal)."""
    if platform.startswith("linux"):
        return ProcFdChecker()
    return NoOpenFileCheck()
