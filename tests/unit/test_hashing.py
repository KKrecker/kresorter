"""Hashing: streaming BLAKE2b and duplicate-candidate hashing with size grouping.

Pipeline: group by size -> partial hash (first bytes) -> full hash only on partial collisions.
Files that changed since the scan (or during hashing) are reported, never hashed as-is.
"""

import hashlib
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from kresorter.core import hashing
from kresorter.core.hashing import (
    Digests,
    HashedFile,
    group_by_size,
    hash_duplicate_candidates,
    hash_file,
)
from kresorter.core.models import FileEntry, Skipped, SkipReason
from support.host import MTIME_STEP_NS


def blake(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def make(path: Path, data: bytes) -> FileEntry:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    info = path.stat()
    return FileEntry(path=path, size=info.st_size, mtime_ns=info.st_mtime_ns)


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


def test_partial_mismatch_skips_full_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = spy_hash_file(monkeypatch)
    a = make(tmp_path / "a", b"AAAA-tail")
    b = make(tmp_path / "b", b"BBBB-tail")

    assert candidates([a, b]) == []
    assert sorted(calls) == [(a.path, 4), (b.path, 4)]  # side by side (decision 0018, 15)


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
    ghost = FileEntry(path=tmp_path / "ghost", size=len(data), mtime_ns=0)

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
    os.utime(b.path, ns=(b.mtime_ns + 10**10, b.mtime_ns + 10**10))
    calls = spy_hash_file(monkeypatch)

    assert candidates([a, b]) == [
        Skipped(path=b.path, reason=SkipReason.CHANGED, detail="modified since scan")
    ]
    assert [path for path, _ in calls] == [a.path]


def test_one_nanosecond_change_is_detected(tmp_path: Path) -> None:
    # A float st_mtime (~1.7e9 s) cannot represent 1 ns; mtime_ns can. NTFS keeps 100 ns steps,
    # which a float cannot represent either.
    a = make(tmp_path / "a", b"data-data")
    b = make(tmp_path / "b", b"data-data")
    os.utime(b.path, ns=(b.mtime_ns + MTIME_STEP_NS, b.mtime_ns + MTIME_STEP_NS))

    assert candidates([a, b]) == [
        Skipped(path=b.path, reason=SkipReason.CHANGED, detail="modified since scan")
    ]


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
            os.utime(path, ns=(b.mtime_ns + 10**10, b.mtime_ns + 10**10))
        return digest

    monkeypatch.setattr(hashing, "hash_file", mutate_b)

    assert candidates([a, b]) == [
        Skipped(path=b.path, reason=SkipReason.CHANGED, detail="modified during hashing")
    ]


# --- side by side (decision 0018, item 15) ------------------------------------------------------


def test_hashing_runs_in_up_to_four_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0018.15] The prefixes of eight candidates: four at once, twice.
    entries = [make(tmp_path / f"f{n}", bytes([n]) * 8) for n in range(8)]
    barrier = threading.Barrier(4, timeout=5)
    lock = threading.Lock()
    running = [0, 0]  # now, most
    real = hashing.hash_file

    def side_by_side(path: Path, *, limit: int | None = None, chunk_size: int = 1 << 20) -> str:
        with lock:
            running[0] += 1
            running[1] = max(running)
        barrier.wait()
        with lock:
            running[0] -= 1
        return real(path, limit=limit, chunk_size=chunk_size)

    monkeypatch.setattr(hashing, "hash_file", side_by_side)
    assert candidates(entries) == []
    assert running == [0, 4]


def test_side_by_side_the_groups_their_order_and_the_skipped_paths_are_those_of_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0018.15] Size groups in the order of the entries, the skipped of each stage before its
    # digests, a small file's prefix its digest; a later file's hash ending first.
    big = b"SAME-" + b"x" * 20
    a = make(tmp_path / "a", big)
    small1, small2 = make(tmp_path / "s1", b"abc"), make(tmp_path / "s2", b"abc")
    b = make(tmp_path / "b", big)
    c = make(tmp_path / "c", b"SAME-" + b"y" * 20)
    ghost = FileEntry(path=tmp_path / "ghost", size=len(big), mtime_ns=0)
    other = make(tmp_path / "o", b"OTHER" + b"x" * 20)
    real = hashing.hash_file
    order = [a, small1, small2, b, ghost, c, other]

    def later_first(path: Path, *, limit: int | None = None, chunk_size: int = 1 << 20) -> str:
        time.sleep(0.002 * (len(order) - [e.path for e in order].index(path)))
        return real(path, limit=limit, chunk_size=chunk_size)

    monkeypatch.setattr(hashing, "hash_file", later_first)
    assert candidates(order) == [
        Skipped(path=ghost.path, reason=SkipReason.NOT_FOUND),
        HashedFile(a, blake(big)),
        HashedFile(b, blake(big)),
        HashedFile(c, blake(c.path.read_bytes())),
        HashedFile(small1, blake(b"abc")),
        HashedFile(small2, blake(b"abc")),
    ]


# --- the digests kept while the window is open [0020.18] ---------------------------------------


def touched(path: Path, data: bytes, after: FileEntry) -> FileEntry:
    """``path`` holding ``data``, modified a step after ``after`` was."""
    path.write_bytes(data)
    os.utime(path, ns=(after.mtime_ns, after.mtime_ns + MTIME_STEP_NS))
    info = path.stat()
    return FileEntry(path=path, size=info.st_size, mtime_ns=info.st_mtime_ns)


def test_with_the_digests_kept_a_second_hashing_reads_no_unchanged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0020.18] The prefixes and the full digests, each by its file's path, size and mtime_ns.
    big = b"SAME-" + b"x" * 20
    order = [make(tmp_path / "a", big), make(tmp_path / "b", big)]
    order += [make(tmp_path / "s1", b"abc"), make(tmp_path / "s2", b"abc")]
    kept = Digests()
    first = list(hash_duplicate_candidates(order, partial_bytes=4, digests=kept))
    calls = spy_hash_file(monkeypatch)
    assert list(hash_duplicate_candidates(order, partial_bytes=4, digests=kept)) == first
    assert calls == []


def test_a_file_changed_since_it_was_hashed_is_read_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0020.18] Its size or mtime_ns no longer those kept: its new digests are kept instead.
    big = b"SAME-" + b"x" * 20
    a, b = make(tmp_path / "a", big), make(tmp_path / "b", big)
    kept = Digests()
    list(hash_duplicate_candidates([a, b], partial_bytes=4, digests=kept))
    changed = touched(b.path, b"SAME-" + b"y" * 20, b)
    calls = spy_hash_file(monkeypatch)
    again = list(hash_duplicate_candidates([a, changed], partial_bytes=4, digests=kept))
    assert again == [HashedFile(a, blake(big)), HashedFile(changed, blake(b"SAME-" + b"y" * 20))]
    assert calls == [(b.path, 4), (b.path, None)]
    calls.clear()
    list(hash_duplicate_candidates([a, changed], partial_bytes=4, digests=kept))
    assert calls == []


def test_a_file_that_could_not_be_hashed_is_not_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0020.18] Changed while it was read: asked again, it is read again.
    a, b = make(tmp_path / "a", b"same"), make(tmp_path / "b", b"same")
    kept = Digests()
    real = hashing.hash_file

    def changing(path: Path, *, limit: int | None = None, chunk_size: int = 1 << 20) -> str:
        digest = real(path, limit=limit, chunk_size=chunk_size)
        if path == b.path:
            os.utime(path, ns=(b.mtime_ns, b.mtime_ns + MTIME_STEP_NS))
        return digest

    monkeypatch.setattr(hashing, "hash_file", changing)
    first = list(hash_duplicate_candidates([a, b], partial_bytes=8, digests=kept))
    assert first == [Skipped(b.path, SkipReason.CHANGED, detail="modified during hashing")]
    info = b.path.stat()
    now = FileEntry(path=b.path, size=info.st_size, mtime_ns=info.st_mtime_ns)
    calls = spy_hash_file(monkeypatch)
    list(hash_duplicate_candidates([a, now], partial_bytes=8, digests=kept))
    assert calls == [(b.path, 8)]
