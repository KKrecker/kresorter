"""Scanner: policy + walker + junk heuristics + duplicate hashing -> a read-only report."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from safeclean.core import hashing
from safeclean.core.heuristics import JunkClassifier, JunkMatch
from safeclean.core.models import FileEntry, Skipped
from safeclean.core.open_files import OpenFileChecker
from safeclean.core.policy import PathPolicy
from safeclean.core.walker import walk


@dataclass(frozen=True)
class ScanContext:
    policy: PathPolicy
    open_files: OpenFileChecker
    classifier: JunkClassifier
    open_files_checked: bool  # False: no real open-file backend; must be disclosed


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
    junk: tuple[JunkFinding, ...]
    duplicates: tuple[DuplicateGroup, ...]
    skipped: tuple[Skipped, ...]


def scan(
    roots: Sequence[Path], context: ScanContext, *, hash_duplicates: bool = True
) -> ScanReport:
    """Walk ``roots`` and build a report. Reads only; never modifies the filesystem."""
    entries: list[FileEntry] = []
    skipped: list[Skipped] = []
    for event in walk(roots, context.policy, context.open_files):
        if isinstance(event, FileEntry):
            entries.append(event)
        else:
            skipped.append(event)
    duplicates = _duplicates(entries, skipped) if hash_duplicates else ()
    return ScanReport(
        roots=tuple(roots),
        files_scanned=len(entries),
        bytes_scanned=sum(e.size for e in entries),
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
