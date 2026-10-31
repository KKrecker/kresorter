"""Walker: safe directory traversal on a real temporary tree.

Never follows symlinks/junctions, prunes blacklisted directories, reports every skip with a
reason and keeps going after errors. OS failures are injected by patching ``os.scandir``.
"""

import os
from collections.abc import Callable, Iterator
from pathlib import Path, PurePath
from typing import Any

import pytest

from fakes import FakeOpenFiles
from safeclean.core.models import FileEntry, Skipped, SkipReason
from safeclean.core.policy import BlockReason, PathPolicy
from safeclean.core.walker import walk


def make_policy(tmp_path: Path, *blocked: Path) -> PathPolicy:
    return PathPolicy(
        flavor=type(PurePath(tmp_path)),
        case_sensitive=True,
        prefix_rules=[(p, BlockReason.SYSTEM) for p in blocked],
        root_entry_names=(),
        profile=(tmp_path / "users", tmp_path / "users" / "me", [], []),
        default_roots=[],
    )


def write(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def files(events: list[FileEntry | Skipped]) -> list[Path]:
    return [e.path for e in events if isinstance(e, FileEntry)]


def skips(events: list[FileEntry | Skipped]) -> list[Skipped]:
    return [e for e in events if isinstance(e, Skipped)]


def run(tmp_path: Path, roots: list[Path], *blocked: Path, open_files: Any = None) -> list[Any]:
    checker = open_files if open_files is not None else FakeOpenFiles()
    return list(walk(roots, make_policy(tmp_path, *blocked), checker))


def test_yields_nested_files_with_size_and_mtime(tmp_path: Path) -> None:
    root = tmp_path / "root"
    a = write(root / "a.txt", b"hello")
    b = write(root / "sub" / "deep" / "b.bin", b"12")
    os.utime(a, (1_000_000, 1_000_000))

    events = run(tmp_path, [root])

    assert events == [
        FileEntry(path=a, size=5, mtime=1_000_000.0),
        FileEntry(path=b, size=2, mtime=b.stat().st_mtime),
    ]


def test_symlink_to_file_is_skipped_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    target = write(tmp_path / "outside" / "secret.txt")
    link = root / "link.txt"
    root.mkdir()
    link.symlink_to(target)

    events = run(tmp_path, [root])

    assert events == [Skipped(path=link, reason=SkipReason.SYMLINK)]


def test_symlink_to_directory_is_not_descended(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write(tmp_path / "outside" / "secret.txt")
    root.mkdir()
    (root / "dirlink").symlink_to(tmp_path / "outside", target_is_directory=True)

    events = run(tmp_path, [root])

    assert events == [Skipped(path=root / "dirlink", reason=SkipReason.SYMLINK)]


def test_symlinked_root_is_resolved_and_checked_against_policy(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    write(blocked / "a.txt")
    alias = tmp_path / "alias"
    alias.symlink_to(blocked, target_is_directory=True)

    events = run(tmp_path, [alias], blocked)

    assert events == [
        Skipped(path=blocked, reason=SkipReason.BLOCKED, block_reason=BlockReason.SYSTEM)
    ]


def test_blocked_directory_is_pruned(tmp_path: Path) -> None:
    root = tmp_path / "root"
    keep = write(root / "keep.txt")
    write(root / "system" / "inner" / "x.dll")

    events = run(tmp_path, [root], root / "system")

    assert files(events) == [keep]
    assert skips(events) == [
        Skipped(path=root / "system", reason=SkipReason.BLOCKED, block_reason=BlockReason.SYSTEM)
    ]


def test_open_file_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "root"
    busy = write(root / "busy.log")
    free = write(root / "free.log")

    events = run(tmp_path, [root], open_files=FakeOpenFiles([busy]))

    assert files(events) == [free]
    assert skips(events) == [
        Skipped(path=busy, reason=SkipReason.BLOCKED, block_reason=BlockReason.OPEN_FILE)
    ]


def test_missing_root_is_reported(tmp_path: Path) -> None:
    missing = tmp_path / "nope"

    assert run(tmp_path, [missing]) == [Skipped(path=missing, reason=SkipReason.NOT_FOUND)]


def test_file_root_is_yielded(tmp_path: Path) -> None:
    f = write(tmp_path / "single.txt", b"abc")

    assert files(run(tmp_path, [f])) == [f]


def test_overlapping_roots_yield_each_file_once(tmp_path: Path) -> None:
    root = tmp_path / "root"
    a = write(root / "sub" / "a.txt")

    assert files(run(tmp_path, [root, root / "sub", root])) == [a]


def test_special_files_are_skipped(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    fifo = root / "pipe"
    os.mkfifo(fifo)

    assert run(tmp_path, [root]) == [Skipped(path=fifo, reason=SkipReason.SPECIAL)]


def failing_scandir(
    monkeypatch: pytest.MonkeyPatch, bad: Path, error: OSError
) -> Callable[..., Any]:
    real = os.scandir

    def fake(path: Any) -> Any:
        if Path(path) == bad:
            raise error
        return real(path)

    monkeypatch.setattr(os, "scandir", fake)
    return fake


def test_permission_denied_directory_is_reported_and_walk_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    write(root / "locked" / "x.txt")
    ok = write(root / "open" / "y.txt")
    failing_scandir(monkeypatch, root / "locked", PermissionError(13, "denied"))

    events = run(tmp_path, [root])

    assert files(events) == [ok]
    assert skips(events) == [Skipped(path=root / "locked", reason=SkipReason.PERMISSION_DENIED)]


def test_unreadable_directory_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    failing_scandir(monkeypatch, root, OSError(5, "I/O error"))

    events = run(tmp_path, [root])

    assert events == [Skipped(path=root, reason=SkipReason.UNREADABLE, detail="I/O error")]


class FakeEntry:
    """os.DirEntry stand-in for cases a Linux tmp dir cannot produce (junctions, races)."""

    def __init__(self, path: Path, *, junction: bool = False, stat_error: bool = False) -> None:
        self.path = str(path)
        self.name = path.name
        self._junction = junction
        self._stat_error = stat_error

    def is_symlink(self) -> bool:
        return False

    def is_junction(self) -> bool:
        return self._junction

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return self._junction

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        return not self._junction

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        if self._stat_error:
            raise FileNotFoundError(2, "gone")
        # st_size=7, st_mtime=42.0 (float fields follow the 10 integer ones)
        return os.stat_result((0o100644, 0, 0, 1, 0, 0, 7, 0, 42, 0, 0.0, 42.0, 0.0))


def fake_listing(monkeypatch: pytest.MonkeyPatch, root: Path, entries: list[FakeEntry]) -> None:
    class Listing:
        def __enter__(self) -> Iterator[FakeEntry]:
            return iter(entries)

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(os, "scandir", lambda path: Listing())


def test_windows_junction_is_treated_as_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    fake_listing(monkeypatch, root, [FakeEntry(root / "junction", junction=True)])

    assert run(tmp_path, [root]) == [Skipped(path=root / "junction", reason=SkipReason.SYMLINK)]


def test_file_vanishing_during_walk_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    fake_listing(
        monkeypatch, root, [FakeEntry(root / "gone.txt", stat_error=True), FakeEntry(root / "b")]
    )

    events = run(tmp_path, [root])

    # Sorted by name: "b" < "gone.txt".
    assert events == [
        FileEntry(path=root / "b", size=7, mtime=42.0),
        Skipped(path=root / "gone.txt", reason=SkipReason.NOT_FOUND),
    ]
