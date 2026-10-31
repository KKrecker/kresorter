"""Plain, immutable records produced by the scanner core."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from safeclean.core.policy import BlockReason


@dataclass(frozen=True)
class FileEntry:
    """A regular file the walker visited. ``path`` is resolved (no symlinks in it)."""

    path: Path
    size: int
    mtime: float


class SkipReason(StrEnum):
    SYMLINK = "symlink"  # symlinks and Windows junctions: never followed
    BLOCKED = "blocked"  # rejected by PathPolicy; see Skipped.block_reason
    SPECIAL = "special"  # FIFOs, sockets, devices
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    UNREADABLE = "unreadable"  # any other OS error; see Skipped.detail


@dataclass(frozen=True)
class Skipped:
    """Something the walker did not visit, with the reason. Reported, never silently dropped."""

    path: Path
    reason: SkipReason
    block_reason: BlockReason | None = None
    detail: str = ""
