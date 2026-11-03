"""Boundary for "is this file currently open by some process?".

The engine depends only on this protocol so tests can use fakes and a checker failure can be
treated as "open" (fail closed). ``reliable`` says whether a "not open" answer can be trusted
for actions: the quarantine refuses to start with an unreliable checker (decision 0004).
"""

from pathlib import PurePath
from typing import Protocol


class OpenFileCheckError(OSError):
    """The backend could not determine open state. Callers must treat the file as open."""


class OpenFileChecker(Protocol):
    @property
    def reliable(self) -> bool:
        """True if "not open" can be trusted for actions (a real OS backend)."""
        ...

    def is_open(self, path: PurePath) -> bool:
        """Return True if any process holds ``path`` open. May raise on backend failure."""
        ...


class NoOpenFileCheck:
    """Placeholder for platforms without a backend: reports nothing as open.

    Only acceptable for read-only reports, and callers must disclose it
    (``ScanContext.open_files_checked = False``). ``reliable`` is False, so actions refuse to run
    with it (decisions 0003, 0004).
    """

    @property
    def reliable(self) -> bool:
        return False

    def is_open(self, path: PurePath) -> bool:
        return False
