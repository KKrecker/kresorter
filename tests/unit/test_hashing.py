"""Hashing: streaming BLAKE2b and duplicate-candidate hashing with size grouping.

Pipeline: group by size -> partial hash (first bytes) -> full hash only on partial collisions.
Files that changed since the scan (or during hashing) are reported, never hashed as-is.
"""

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from safeclean.core import hashing
from safeclean.core.hashing import (
    HashedFile,
    group_by_size,
    hash_duplicate_candidates,
    hash_file,
)
from safeclean.core.models import FileEntry, Skipped, SkipReason


def blake(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def make(path: Path, data: bytes) -> FileEntry:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    info = path.stat()
    return FileEntry(path=path, size=info.st_size, mtime=info.st_mtime)


def spy_hash_file(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, int | None]]:
    calls: list[tuple[Path, int | None]] = []
    real = hashing.hash_file

    def spy(path: Path, *, limit: int | None = None, chunk_size: int = 1 << 20) -> str:
        calls.append((path, limit))
        return real(path, limit=limit, chunk_size=chunk_size)

    monkeypatch.setattr(hashing, "hash_file", spy)
    return calls


def candidates(entries: list[FileEntry], partial: int = 4) -> list[HashedFile | Skipped]:
    return list(hash_duplicate_candidates(entries, partial_bytes=partial))


# --- hash_file ---------------------------------------------------------------------------------


def test_hash_file_streams_in_chunks(tmp_path: Path) -> None:
    data = os.urandom(10_000)
    path = tmp_path / "f"
    path.write_bytes(data)

    assert hash_file(path, chunk_size=1000) == blake(data)


def test_hash_file_of_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty"
    path.write_bytes(b"")

    assert hash_file(path) == blake(b"")


@pytest.mark.parametrize("limit", [0, 1, 999, 1000, 1001, 5000])
def test_hash_file_limit_hashes_prefix_only(tmp_path: Path, limit: int) -> None:
    data = os.urandom(3000)
    path = tmp_path / "f"
    path.write_bytes(data)

    assert hash_file(path, limit=limit, chunk_size=1000) == blake(data[:limit])


@pytest.mark.parametrize(
    "kwargs", [{"chunk_size": 0}, {"chunk_size": -1}, {"limit": -1}], ids=["zero", "neg", "lim"]
)
def test_hash_file_rejects_bad_arguments(tmp_path: Path, kwargs: dict[str, Any]) -> None:
    path = tmp_path / "f"
    path.write_bytes(b"x")

    with pytest.raises(ValueError, match="must be"):
        hash_file(path, **kwargs)


# --- group_by_size -----------------------------------------------------------------------------


def test_group_by_size_keeps_only_shared_sizes_and_skips_empty(tmp_path: Path) -> None:
    a = make(tmp_path / "a", b"123")
    b = make(tmp_path / "b", b"abc")
    lone = make(tmp_path / "lone", b"12345")
    e1 = make(tmp_path / "e1", b"")
    e2 = make(tmp_path / "e2", b"")

    assert group_by_size([a, lone, e1, b, e2]) == {3: [a, b]}


# --- hash_duplicate_candidates -----------------------------------------------------------------


def test_identical_files_get_equal_full_digests(tmp_path: Path) -> None:
    data = b"same content, longer than partial"
    a = make(tmp_path / "a", data)
    b = make(tmp_path / "b", data)

    assert candidates([a, b]) == [HashedFile(a, blake(data)), HashedFile(b, blake(data))]


def test_unique_size_is_never_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = spy_hash_file(monkeypatch)
    lone = make(tmp_path / "lone", b"12345")

    assert candidates([lone]) == []
    assert calls == []


def test_partial_mismatch_skips_full_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = spy_hash_file(monkeypatch)
    a = make(tmp_path / "a", b"AAAA-tail")
    b = make(tmp_path / "b", b"BBBB-tail")

    assert candidates([a, b]) == []
    assert calls == [(a.path, 4), (b.path, 4)]


def test_same_prefix_different_tail_is_fully_hashed(tmp_path: Path) -> None:
    a = make(tmp_path / "a", b"SAME-tail1")
    b = make(tmp_path / "b", b"SAME-tail2")

    assert candidates([a, b]) == [
        HashedFile(a, blake(b"SAME-tail1")),
        HashedFile(b, blake(b"SAME-tail2")),
    ]


def test_small_files_are_read_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = spy_hash_file(monkeypatch)
    a = make(tmp_path / "a", b"abc")
    b = make(tmp_path / "b", b"abc")

    # size <= partial_bytes: the prefix hash IS the full hash.
    assert candidates([a, b]) == [HashedFile(a, blake(b"abc")), HashedFile(b, blake(b"abc"))]
    assert len(calls) == 2


def test_vanished_file_is_reported_and_rest_still_compared(tmp_path: Path) -> None:
    data = b"duplicate data"
    a = make(tmp_path / "a", data)
    b = make(tmp_path / "b", data)
    ghost = FileEntry(path=tmp_path / "ghost", size=len(data), mtime=0.0)

    assert candidates([a, ghost, b]) == [
        Skipped(path=ghost.path, reason=SkipReason.NOT_FOUND),
        HashedFile(a, blake(data)),
        HashedFile(b, blake(data)),
    ]


def test_permission_denied_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a = make(tmp_path / "a", b"data")
    b = make(tmp_path / "b", b"data")

    def deny(path: Path, *, limit: int | None = None, chunk_size: int = 1 << 20) -> str:
        raise PermissionError(13, "denied")

    monkeypatch.setattr(hashing, "hash_file", deny)

    assert candidates([a, b]) == [
        Skipped(path=a.path, reason=SkipReason.PERMISSION_DENIED),
        Skipped(path=b.path, reason=SkipReason.PERMISSION_DENIED),
    ]


def test_file_changed_since_scan_is_not_hashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = make(tmp_path / "a", b"data-data")
    b = make(tmp_path / "b", b"data-data")
    os.utime(b.path, (b.mtime + 10, b.mtime + 10))
    calls = spy_hash_file(monkeypatch)

    assert candidates([a, b]) == [
        Skipped(path=b.path, reason=SkipReason.CHANGED, detail="modified since scan")
    ]
    assert [path for path, _ in calls] == [a.path]


def test_file_changed_during_hashing_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = make(tmp_path / "a", b"data-data")
    b = make(tmp_path / "b", b"data-data")
    real: Callable[..., str] = hashing.hash_file

    def mutate_b(path: Path, *, limit: int | None = None, chunk_size: int = 1 << 20) -> str:
        digest = real(path, limit=limit, chunk_size=chunk_size)
        if path == b.path:
            path.write_bytes(b"other-dat")
            os.utime(path, (b.mtime + 10, b.mtime + 10))
        return digest

    monkeypatch.setattr(hashing, "hash_file", mutate_b)

    assert candidates([a, b]) == [
        Skipped(path=b.path, reason=SkipReason.CHANGED, detail="modified during hashing")
    ]
