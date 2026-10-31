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
