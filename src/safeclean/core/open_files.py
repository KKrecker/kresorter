"""Boundary for "is this file currently open by some process?".

Real, OS-specific implementations come later; the engine depends only on this protocol so tests
can use fakes and a checker failure can be treated as "open" (fail closed).
"""

from pathlib import PurePath
from typing import Protocol


class OpenFileChecker(Protocol):
    def is_open(self, path: PurePath) -> bool:
        """Return True if any process holds ``path`` open. May raise on backend failure."""
        ...


class NoOpenFileCheck:
    """Placeholder until OS backends exist: reports nothing as open.

    Only acceptable for read-only reports, and callers must disclose it
    (``ScanContext.open_files_checked = False``). Actions (quarantine, step 2) must refuse to run
    without a real checker (decision 0003).
    """

    def is_open(self, path: PurePath) -> bool:
        return False
