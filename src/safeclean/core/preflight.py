"""Preflight: re-validate one candidate right before a domain acts on it (decision 0004, item 5).

The quarantine and organize both use it (decision 0012, amending 0004).

Order (first failing check wins, cheap before expensive):

1. policy blacklist (pure, no disk access);
2. the file on disk: parent chain not swapped for a link, ``lstat`` is a regular file (not a
   symlink), ``size`` and ``mtime_ns`` equal the scan;
3. for duplicates, the twin that stays: exists, is a regular file with the scanned stat, is not
   the same inode, and still has the group digest;
4. open files last (a full ``/proc`` scan on Linux); a failing checker counts as open.

Not atomic with the move: the file can change between preflight and the rename. That window is
inherent, which is why journal-before-move and ``recover()`` stay mandatory.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from safeclean.core.hashing import hash_file
from safeclean.core.models import FileEntry
from safeclean.core.open_files import OpenFileChecker
from safeclean.core.policy import BlockReason, PathPolicy


class UnreliableCheckerError(RuntimeError):
    """Raised when actions are attempted without a reliable open-file checker."""


class RefusalReason(StrEnum):
    BLOCKED = "blocked"  # policy blacklist; see Refused.block_reason
    OPEN_FILE = "open_file"  # held open by a process, or the checker failed
    NOT_FOUND = "not_found"
    UNREADABLE = "unreadable"  # any other OS error; see Refused.detail
    SYMLINK = "symlink"
    NOT_REGULAR = "not_regular"  # directory, FIFO, socket, device
    CHANGED = "changed"  # size or mtime_ns differ from the scan
    PARENT_SWAPPED = "parent_swapped"  # a directory on the path is now a link
    TWIN_MISSING = "twin_missing"  # the copy that stays is gone or unreadable
    TWIN_CHANGED = "twin_changed"  # the copy that stays is no longer the scanned one
    TWIN_SAME_FILE = "twin_same_file"  # hard link: moving frees nothing
    CROSS_DEVICE = "cross_device"  # not on the destination's device; checked by the domain
    DUPLICATE_CANDIDATE = "duplicate_candidate"  # same path twice in one batch; by the service


@dataclass(frozen=True)
class Candidate:
    """A scanned file to act on; for duplicates, the twin that stays and the group digest."""

    entry: FileEntry
    twin: FileEntry | None = None
    digest: str | None = None

    def __post_init__(self) -> None:
        if self.twin is None:
            return
        if self.digest is None:
            raise ValueError("a twin requires the group digest")
        if self.twin.path == self.entry.path:
            raise ValueError("a file cannot be its own twin (itself)")


@dataclass(frozen=True)
class Cleared:
    candidate: Candidate
    stat: os.stat_result  # fresh lstat: st_dev for CROSS_DEVICE, st_mode for the journal


@dataclass(frozen=True)
class Refused:
    path: Path
    reason: RefusalReason
    block_reason: BlockReason | None = None
    detail: str = ""


class Preflight:
    def __init__(self, policy: PathPolicy, open_files: OpenFileChecker) -> None:
        if not open_files.reliable:
            raise UnreliableCheckerError("actions need a reliable open-file checker")
        self._policy = policy
        self._open_files = open_files

    def check(self, candidate: Candidate) -> Cleared | Refused:
        path = candidate.entry.path
        verdict = self._policy.check_path(path)
        if not verdict.allowed:
            return Refused(path, RefusalReason.BLOCKED, block_reason=verdict.reason)
        on_disk = _check_on_disk(candidate.entry)
        if isinstance(on_disk, Refused):
            return on_disk
        if candidate.twin is not None:
            refusal = _check_twin(path, on_disk, candidate.twin, candidate.digest)
            if refusal is not None:
                return refusal
        verdict = self._policy.check_file(path, self._open_files)
        if not verdict.allowed:
            return Refused(path, RefusalReason.OPEN_FILE, block_reason=verdict.reason)
        return Cleared(candidate, on_disk)


def _check_on_disk(entry: FileEntry) -> os.stat_result | Refused:
    path = entry.path
    if path.parent.resolve() != path.parent:
        return Refused(path, RefusalReason.PARENT_SWAPPED)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return Refused(path, RefusalReason.NOT_FOUND)
    except OSError as error:
        return Refused(path, RefusalReason.UNREADABLE, detail=error.strerror or str(error))
    if stat.S_ISLNK(info.st_mode):
        return Refused(path, RefusalReason.SYMLINK)
    if not stat.S_ISREG(info.st_mode):
        return Refused(path, RefusalReason.NOT_REGULAR)
    if (info.st_size, info.st_mtime_ns) != (entry.size, entry.mtime_ns):
        return Refused(path, RefusalReason.CHANGED)
    return info


def _check_twin(
    path: Path, info: os.stat_result, twin: FileEntry, digest: str | None
) -> Refused | None:
    try:
        twin_info = twin.path.lstat()
        same_stat = (twin_info.st_size, twin_info.st_mtime_ns) == (twin.size, twin.mtime_ns)
        if not stat.S_ISREG(twin_info.st_mode) or not same_stat:
            return Refused(path, RefusalReason.TWIN_CHANGED, detail=str(twin.path))
        if (twin_info.st_dev, twin_info.st_ino) == (info.st_dev, info.st_ino):
            return Refused(path, RefusalReason.TWIN_SAME_FILE, detail=str(twin.path))
        if hash_file(twin.path) != digest:
            return Refused(path, RefusalReason.TWIN_CHANGED, detail=str(twin.path))
    except OSError as error:  # gone or unreadable: the copy that stays cannot be confirmed
        detail = f"{twin.path}: {error.strerror or error}"
        return Refused(path, RefusalReason.TWIN_MISSING, detail=detail)
    return None
