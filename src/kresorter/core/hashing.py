"""Content hashing for duplicate detection.

Pipeline (cheapest first): group by size -> hash a prefix -> full hash only on prefix
collisions. Every file is re-checked against its scan record before and after reading; a file
that changed is reported as CHANGED instead of being hashed as-is. The prefixes, then the full
digests, are computed side by side in up to ``HASH_THREADS`` threads; what is yielded, and its
order, is that of one file after another (decision 0018, item 15). The digests of the files
hashed may be kept (``Digests``): asked again about a file whose size and ``mtime_ns`` are those
it was hashed with, the hashing reads it no more (decision 0020, item 18).
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from hashlib import blake2b
from itertools import chain
from pathlib import Path

from kresorter.core.models import FileEntry, Skipped, SkipReason, skipped_from_os_error

DIGEST_SIZE = 32
DEFAULT_CHUNK = 1 << 20
DEFAULT_PARTIAL = 64 * 1024
HASH_THREADS = 4


@dataclass(frozen=True)
class HashedFile:
    entry: FileEntry
    digest: str


class Digests:
    """The prefix and full digests of the files hashed, each kept with its file's path, size
    and ``mtime_ns``: one version of a file each, a changed one's replacing it. In memory only,
    as long as whoever made it keeps it (the window, decision 0020, item 18)."""

    def __init__(self) -> None:
        self._known: dict[Path, tuple[int, int, dict[int | None, str]]] = {}

    def get(self, entry: FileEntry, limit: int | None) -> str | None:
        """The digest of ``entry``'s first ``limit`` bytes (``None``: all), when it is kept for
        its size and ``mtime_ns``."""
        known = self._known.get(entry.path)
        if known is None or known[:2] != (entry.size, entry.mtime_ns):
            return None
        return known[2].get(limit)

    def keep(self, entry: FileEntry, limit: int | None, digest: str) -> None:
        known = self._known.get(entry.path)
        if known is None or known[:2] != (entry.size, entry.mtime_ns):
            known = (entry.size, entry.mtime_ns, {})
            self._known[entry.path] = known
        known[2][limit] = digest


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
    entries: Iterable[FileEntry],
    *,
    partial_bytes: int = DEFAULT_PARTIAL,
    digests: Digests | None = None,
) -> Iterator[HashedFile | Skipped]:
    """Yield full digests for files that may be duplicates, and Skipped for unreadable/changed.

    Files whose size or prefix is unique are dropped silently: they cannot be duplicates. The
    digests read are kept in ``digests``, and those kept there are not read again.
    """
    kept = Digests() if digests is None else digests
    groups = list(group_by_size(entries).items())
    with ThreadPoolExecutor(HASH_THREADS) as pool:
        hashes = partial(_hashes, pool, kept=kept)
        prefixes = hashes([e for _, group in groups for e in group], partial_bytes)
        stages = [_prefix_stage(group, prefixes) for _, group in groups]
        large = [
            hashed.entry
            for (size, _), (_, collisions) in zip(groups, stages, strict=True)
            if size > partial_bytes
            for collision in collisions
            for hashed in collision
        ]
        fulls = hashes(large, None)
    for (size, _), (skipped, collisions) in zip(groups, stages, strict=True):
        yield from skipped
        for collision in collisions:
            if size <= partial_bytes:
                yield from collision  # the prefix covered the whole file
            else:
                full_skipped, full = _split([h.entry for h in collision], fulls)
                yield from full_skipped
                yield from full


def _hashes(
    pool: ThreadPoolExecutor, entries: list[FileEntry], limit: int | None, *, kept: Digests
) -> dict[FileEntry, str | Skipped]:
    """Each entry's digest (or why it has none): those kept as they are, the others side by
    side: the prefixes, each as short as the next, in one slice of the entries per thread, a
    full digest in a task of its own; each digest read is kept."""
    known = {entry: kept.get(entry, limit) for entry in entries}
    unread = [entry for entry, digest in known.items() if digest is None]
    size = 1 if limit is None else max(1, -(-len(unread) // HASH_THREADS))
    batches = [unread[i : i + size] for i in range(0, len(unread), size)]
    results = chain.from_iterable(pool.map(partial(_hash_batch, limit=limit), batches))
    read = dict(zip(unread, results, strict=True))
    for entry, result in read.items():
        if isinstance(result, str):
            kept.keep(entry, limit, result)
    return {entry: digest if digest is not None else read[entry] for entry, digest in known.items()}


def _hash_batch(entries: list[FileEntry], limit: int | None) -> list[str | Skipped]:
    return [_stable_hash(entry, limit) for entry in entries]


def _split(
    group: list[FileEntry], results: dict[FileEntry, str | Skipped]
) -> tuple[list[Skipped], list[HashedFile]]:
    """The skipped of ``group`` and its hashed files, each in its order."""
    skipped: list[Skipped] = []
    hashed: list[HashedFile] = []
    for entry in group:
        result = results[entry]
        if isinstance(result, Skipped):
            skipped.append(result)
        else:
            hashed.append(HashedFile(entry, result))
    return skipped, hashed


def _prefix_stage(
    group: list[FileEntry], prefixes: dict[FileEntry, str | Skipped]
) -> tuple[list[Skipped], list[list[HashedFile]]]:
    """The skipped of ``group``, and its files whose prefixes collide."""
    skipped, hashed = _split(group, prefixes)
    return skipped, list(_collisions(hashed))


def _collisions(hashed: list[HashedFile]) -> Iterator[list[HashedFile]]:
    by_digest: dict[str, list[HashedFile]] = defaultdict(list)
    for item in hashed:
        by_digest[item.digest].append(item)
    return (group for group in by_digest.values() if len(group) > 1)


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
