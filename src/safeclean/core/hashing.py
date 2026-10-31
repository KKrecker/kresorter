"""Content hashing for duplicate detection.

Pipeline (cheapest first): group by size -> hash a prefix -> full hash only on prefix
collisions. Every file is re-checked against its scan record before and after reading; a file
that changed is reported as CHANGED instead of being hashed as-is.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from hashlib import blake2b
from pathlib import Path

from safeclean.core.models import FileEntry, Skipped, SkipReason, skipped_from_os_error

DIGEST_SIZE = 32
DEFAULT_CHUNK = 1 << 20
DEFAULT_PARTIAL = 64 * 1024


@dataclass(frozen=True)
class HashedFile:
    entry: FileEntry
    digest: str


def hash_file(path: Path, *, limit: int | None = None, chunk_size: int = DEFAULT_CHUNK) -> str:
    """Streaming BLAKE2b (32-byte digest) of the file, or of its first ``limit`` bytes."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")
    digest = blake2b(digest_size=DIGEST_SIZE)
    remaining = limit
    with path.open("rb") as stream:
        while remaining is None or remaining > 0:
            chunk = stream.read(chunk_size if remaining is None else min(chunk_size, remaining))
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return digest.hexdigest()


def group_by_size(entries: Iterable[FileEntry], *, min_size: int = 1) -> dict[int, list[FileEntry]]:
    """Sizes shared by at least two files (empty files excluded by default), in input order."""
    groups: dict[int, list[FileEntry]] = defaultdict(list)
    for entry in entries:
        if entry.size >= min_size:
            groups[entry.size].append(entry)
    return {size: group for size, group in groups.items() if len(group) > 1}


def hash_duplicate_candidates(
    entries: Iterable[FileEntry], *, partial_bytes: int = DEFAULT_PARTIAL
) -> Iterator[HashedFile | Skipped]:
    """Yield full digests for files that may be duplicates, and Skipped for unreadable/changed.

    Files whose size or prefix is unique are dropped silently: they cannot be duplicates.
    """
    for size, group in group_by_size(entries).items():
        prefix_hashed: list[HashedFile] = []
        yield from _hash_all(group, partial_bytes, prefix_hashed)
        for collision in _collisions(prefix_hashed):
            if size <= partial_bytes:
                yield from collision  # the prefix covered the whole file
            else:
                full: list[HashedFile] = []
                yield from _hash_all([h.entry for h in collision], None, full)
                yield from full


def _collisions(hashed: list[HashedFile]) -> Iterator[list[HashedFile]]:
    by_digest: dict[str, list[HashedFile]] = defaultdict(list)
    for item in hashed:
        by_digest[item.digest].append(item)
    return (group for group in by_digest.values() if len(group) > 1)


def _hash_all(
    group: list[FileEntry], limit: int | None, out: list[HashedFile]
) -> Iterator[Skipped]:
    """Hash each entry into ``out``; yield Skipped for the ones that failed."""
    for entry in group:
        result = _stable_hash(entry, limit)
        if isinstance(result, Skipped):
            yield result
        else:
            out.append(HashedFile(entry, result))


def _changed(entry: FileEntry, info: os.stat_result) -> bool:
    return info.st_size != entry.size or info.st_mtime_ns != entry.mtime_ns


def _stable_hash(entry: FileEntry, limit: int | None) -> str | Skipped:
    try:
        if _changed(entry, entry.path.stat()):
            return Skipped(entry.path, SkipReason.CHANGED, detail="modified since scan")
        digest = hash_file(entry.path, limit=limit)
        after = entry.path.stat()
    except OSError as error:
        return skipped_from_os_error(entry.path, error)
    if _changed(entry, after):
        return Skipped(entry.path, SkipReason.CHANGED, detail="modified during hashing")
    return digest
