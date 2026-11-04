"""Scanner: policy + walker + junk heuristics + duplicate hashing -> a read-only report."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from kresorter.core import hashing
from kresorter.core.heuristics import JunkClassifier, JunkMatch, Platform
from kresorter.core.models import FileEntry, Skipped
from kresorter.core.open_files import OpenFileChecker, for_scan
from kresorter.core.policy import PathPolicy
from kresorter.core.walker import walk

if TYPE_CHECKING:
    from kresorter.organize.synced import SyncedFolders

Progress = Callable[[int], None]  # the files read so far (decision 0018, item 16)
PROGRESS_EVERY = 250


@dataclass(frozen=True)
class ScanContext:
    policy: PathPolicy
    open_files: OpenFileChecker
    classifier: JunkClassifier
    open_files_checked: bool  # False: no real open-file backend; must be disclosed
    platform: Platform  # the system it was made for, no default (decision 0012, item 39)
    synced: SyncedFolders  # what organize refuses as a whole, no default (0017, item 10)


@dataclass(frozen=True)
class JunkFinding:
    entry: FileEntry
    match: JunkMatch


@dataclass(frozen=True)
class DuplicateGroup:
    """Files with the same content, as scanned: size and ``mtime_ns`` travel with each copy."""

    digest: str
    entries: tuple[FileEntry, ...]

    def __post_init__(self) -> None:
        if len(self.entries) < 2:
            raise ValueError("a duplicate group needs at least two copies")
        if len({e.size for e in self.entries}) != 1:
            raise ValueError("copies in a duplicate group must have the same size")

    @property
    def size(self) -> int:
        return self.entries[0].size

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(e.path for e in self.entries)

    @property
    def wasted_bytes(self) -> int:
        return self.size * (len(self.entries) - 1)


@dataclass(frozen=True)
class ScanReport:
    roots: tuple[Path, ...]
    files_scanned: int
    bytes_scanned: int
    entries: tuple[FileEntry, ...]  # every scanned file, for analysis
    junk: tuple[JunkFinding, ...]
    duplicates: tuple[DuplicateGroup, ...]
    skipped: tuple[Skipped, ...]


def unreported(read: int) -> None:
    """The progress of a scan no one follows."""


def scan(
    roots: Sequence[Path],
    context: ScanContext,
    *,
    hash_duplicates: bool = True,
    progress: Progress = unreported,
) -> ScanReport:
    """Walk ``roots`` and build a report. Reads only; never modifies the filesystem.
    ``progress`` is called with the files read so far, every ``PROGRESS_EVERY`` files and once
    they are all read."""
    entries: list[FileEntry] = []
    skipped: list[Skipped] = []
    for event in walk(roots, context.policy, for_scan(context.open_files)):
        if isinstance(event, FileEntry):
            entries.append(event)
            if len(entries) % PROGRESS_EVERY == 0:
                progress(len(entries))
        else:
            skipped.append(event)
    if not entries or len(entries) % PROGRESS_EVERY:
        progress(len(entries))
    duplicates = _duplicates(entries, skipped) if hash_duplicates else ()
    return ScanReport(
        roots=tuple(roots),
        files_scanned=len(entries),
        bytes_scanned=sum(e.size for e in entries),
        entries=tuple(entries),
        junk=tuple(_junk(entries, context.classifier)),
        duplicates=duplicates,
        skipped=tuple(skipped),
    )


def _junk(entries: Iterable[FileEntry], classifier: JunkClassifier) -> Iterable[JunkFinding]:
    for entry in entries:
        match = classifier.classify(entry.path)
        if match is not None:
            yield JunkFinding(entry, match)


def _duplicates(entries: list[FileEntry], skipped: list[Skipped]) -> tuple[DuplicateGroup, ...]:
    by_digest: dict[str, list[FileEntry]] = defaultdict(list)
    for result in hashing.hash_duplicate_candidates(entries):
        if isinstance(result, Skipped):
            skipped.append(result)
        else:
            by_digest[result.digest].append(result.entry)
    return tuple(
        DuplicateGroup(digest, tuple(group))
        for digest, group in by_digest.items()
        if len(group) > 1
    )
