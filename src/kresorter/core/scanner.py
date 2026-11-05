"""Scanner: policy + walker + junk heuristics + duplicate hashing -> a read-only report.

The roots read for junk only (the programs' caches, decision 0020, item 15) are walked after
the others: a file found there and in no other root is classified, never compared as a
duplicate nor rated by size or age.

The walk lists without opening a file; once the junk is classified and the duplicates hashed,
the junk files and the copies are asked about being open, and only they (decision 0020, item
17): an open one is skipped and leaves its group. A large or old file, shown for review, is
asked about when it is acted on (preflight). The report says how long each part took (item 19).
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import cached_property, partial
from pathlib import Path
from typing import TYPE_CHECKING

from kresorter.core import hashing
from kresorter.core.heuristics import JunkClassifier, JunkMatch, Platform
from kresorter.core.models import FileEntry, Skipped, SkipReason
from kresorter.core.open_files import OpenFileChecker, for_scan, threads_for
from kresorter.core.policy import BlockReason, PathPolicy, check_open
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
class ScanTimes:
    """How long a scan took, and what took it, in seconds (decision 0020, item 19): listing
    (with classifying the junk), hashing the duplicates, checking for open files."""

    total: float = 0.0
    listing: float = 0.0
    open_checks: float = 0.0
    duplicates: float = 0.0


@dataclass(frozen=True)
class ScanReport:
    roots: tuple[Path, ...]
    files_scanned: int
    bytes_scanned: int
    entries: tuple[FileEntry, ...]  # every scanned file, for analysis
    junk: tuple[JunkFinding, ...]
    duplicates: tuple[DuplicateGroup, ...]
    skipped: tuple[Skipped, ...]
    junk_only_roots: tuple[Path, ...] = ()  # walked after ``roots`` (decision 0020, item 15)
    junk_only: frozenset[Path] = frozenset()  # the files found in them alone
    times: ScanTimes = ScanTimes()

    @cached_property
    def compared(self) -> tuple[FileEntry, ...]:
        """The files compared as duplicates and rated by size and age: every one but those
        read for junk only."""
        if not self.junk_only:
            return self.entries
        return tuple(e for e in self.entries if e.path not in self.junk_only)


def unreported(read: int) -> None:
    """The progress of a scan no one follows."""


def scan(
    roots: Sequence[Path],
    context: ScanContext,
    *,
    junk_only: Sequence[Path] = (),
    hash_duplicates: bool = True,
    digests: hashing.Digests | None = None,
    progress: Progress = unreported,
    clock: Callable[[], float] = time.perf_counter,
) -> ScanReport:
    """Walk ``roots``, then ``junk_only``, and build a report. Reads only; never modifies the
    filesystem. ``progress`` is called with the files read so far, every ``PROGRESS_EVERY``
    files and once they are all read; ``digests``: those kept from the scans before, kept
    for the scans after (decision 0020, item 18); ``clock``: what the times are measured on."""
    started = clock()
    entries: list[FileEntry] = []
    skipped: list[Skipped] = []
    walked = [*roots, *junk_only]
    for event in walk(walked, context.policy):
        if isinstance(event, FileEntry):
            entries.append(event)
            if len(entries) % PROGRESS_EVERY == 0:
                progress(len(entries))
        else:
            skipped.append(event)
    if not entries or len(entries) % PROGRESS_EVERY:
        progress(len(entries))
    junk = list(_junk(entries, context.classifier))
    listed = clock()
    alone = _found_alone(entries, roots, junk_only)
    compared = [e for e in entries if e.path not in alone] if alone else entries
    duplicates = _duplicates(compared, skipped, digests) if hash_duplicates else ()
    hashed = clock()
    asked = [f.entry.path for f in junk] + [path for group in duplicates for path in group.paths]
    held = _held(list(dict.fromkeys(asked)), context.open_files)
    checked = clock()
    if held:
        skipped.extend(
            Skipped(path, SkipReason.BLOCKED, block_reason=BlockReason.OPEN_FILE) for path in held
        )
        entries = [e for e in entries if e.path not in held]
        junk = [f for f in junk if f.entry.path not in held]
        duplicates = _without(duplicates, held)
    return ScanReport(
        roots=tuple(roots),
        files_scanned=len(entries),
        bytes_scanned=sum(e.size for e in entries),
        entries=tuple(entries),
        junk=tuple(junk),
        duplicates=duplicates,
        skipped=tuple(skipped),
        junk_only_roots=tuple(junk_only),
        junk_only=alone.difference(held),
        times=ScanTimes(
            total=checked - started,
            listing=listed - started,
            open_checks=checked - hashed,
            duplicates=hashed - listed,
        ),
    )


def _held(paths: list[Path], open_files: OpenFileChecker) -> dict[Path, None]:
    """The ones of ``paths`` held open, in their order (fail closed: a failing check counts as
    open): the snapshot of every process's open files taken once on Linux (decision 0018, item
    11), up to ``CHECK_THREADS`` share-mode checks at once on Windows (item 12); none asked
    when there is nothing to ask about."""
    if not paths:
        return {}
    check = partial(check_open, open_files=for_scan(open_files))
    threads = threads_for(open_files)
    if threads > 1 and len(paths) > 1:
        with ThreadPoolExecutor(threads) as pool:
            verdicts = list(pool.map(check, paths))
    else:
        verdicts = [check(path) for path in paths]
    return dict.fromkeys(p for p, v in zip(paths, verdicts, strict=True) if not v.allowed)


def _without(
    groups: tuple[DuplicateGroup, ...], held: dict[Path, None]
) -> tuple[DuplicateGroup, ...]:
    """``groups`` without their copies in ``held``; a group left with one copy is none."""
    kept = ((g.digest, tuple(e for e in g.entries if e.path not in held)) for g in groups)
    return tuple(DuplicateGroup(digest, entries) for digest, entries in kept if len(entries) > 1)


def _found_alone(
    entries: Iterable[FileEntry], roots: Sequence[Path], junk_only: Sequence[Path]
) -> frozenset[Path]:
    """The files in ``junk_only`` and in none of ``roots``, by the folders the walker gave
    them: each root resolved as it resolves it, its path and the folders' below it."""
    if not junk_only:
        return frozenset()

    def below(folders: Sequence[Path]) -> tuple[str, ...]:
        resolved = [_resolved(folder) for folder in folders]
        return tuple(str(folder).rstrip(os.sep) + os.sep for folder in resolved if folder)

    inside, chosen = below(junk_only), below(roots)
    return frozenset(
        entry.path
        for entry in entries
        if str(entry.path).startswith(inside) and not str(entry.path).startswith(chosen)
    )


def _resolved(folder: Path) -> Path | None:
    try:
        return folder.resolve(strict=True)
    except OSError:
        return None


def _junk(entries: Iterable[FileEntry], classifier: JunkClassifier) -> Iterable[JunkFinding]:
    for entry in entries:
        match = classifier.classify(entry.path)
        if match is not None:
            yield JunkFinding(entry, match)


def _duplicates(
    entries: list[FileEntry], skipped: list[Skipped], digests: hashing.Digests | None
) -> tuple[DuplicateGroup, ...]:
    by_digest: dict[str, list[FileEntry]] = defaultdict(list)
    for result in hashing.hash_duplicate_candidates(entries, digests=digests):
        if isinstance(result, Skipped):
            skipped.append(result)
        else:
            by_digest[result.digest].append(result.entry)
    return tuple(
        DuplicateGroup(digest, tuple(group))
        for digest, group in by_digest.items()
        if len(group) > 1
    )
