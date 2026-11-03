"""Synced folders made up for a test (decision 0017, items 8 and 10)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePath

from kresorter.organize.synced import SyncedFoldersUnknown


class FakeSynced:
    """``SyncedFolders`` naming ``roots``, or raising ``SyncedFoldersUnknown(error)`` when
    ``error`` is set; ``reads`` counts the times it was asked."""

    def __init__(self, roots: Iterable[PurePath] = (), error: str | None = None) -> None:
        self._roots = tuple(roots)
        self._error = error
        self.reads = 0

    def folders(self) -> tuple[PurePath, ...]:
        self.reads += 1
        if self._error is not None:
            raise SyncedFoldersUnknown(self._error)
        return self._roots
