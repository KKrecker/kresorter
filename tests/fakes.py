"""Fakes for OS boundaries. Tests never touch the live system state they describe."""

import errno
import functools
import os
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePath

import pytest

from safeclean.autostart.registry import Hive, RegistryError, RegValue
from safeclean.core.policy import BlockReason, PathPolicy
from safeclean.storage import db

RegistryKeys = Mapping[tuple[Hive, str], Sequence[RegValue]]


class FakeOpenFiles:
    """Open-file checker that reports a fixed set of paths as open."""

    reliable = True

    def __init__(self, open_paths: Iterable[PurePath] = ()) -> None:
        self._open = {str(p) for p in open_paths}
        self.calls: list[PurePath] = []

    def is_open(self, path: PurePath) -> bool:
        self.calls.append(path)
        return str(path) in self._open


class BrokenOpenFiles:
    """Open-file checker whose backend fails (e.g. access denied to the process list)."""

    reliable = True

    def is_open(self, path: PurePath) -> bool:
        raise OSError("cannot enumerate open handles")


def make_policy(
    tmp_path: Path,
    *blocked: Path,
    default_roots: Iterable[Path] = (),
    app_data_dir: Path | None = None,
) -> PathPolicy:
    """Policy rooted in ``tmp_path``: blocks ``blocked`` (as SYSTEM), no real system paths.

    The app data directory defaults to ``tmp_path / "appdata"`` (blocked as APP_DATA).
    """
    return PathPolicy(
        flavor=type(PurePath(tmp_path)),
        case_sensitive=True,
        prefix_rules=[(p, BlockReason.SYSTEM) for p in blocked],
        root_entry_names=(),
        profile=(tmp_path / "users", tmp_path / "users" / "me", [], []),
        default_roots=list(default_roots),
        app_data_dir=app_data_dir or tmp_path / "appdata",
    )


class FakeRegistry:
    """Registry: keys by (hive, path); a denied key raises like a real one would.

    The sub-keys of a key are the next path parts of the keys below it, in the order given, so
    readers that need a sorted listing must sort it themselves. ``set_user_value`` writes under
    ``HKCU`` only, as ``UserRegistry`` does: every call is recorded in ``writes``, then
    ``write_error`` is raised if set, else the value replaces one of the same name (any case).
    """

    def __init__(
        self,
        keys: RegistryKeys,
        denied: Iterable[tuple[Hive, str]] = (),
        *,
        write_error: BaseException | None = None,
    ) -> None:
        self._keys = dict(keys)
        self._denied = set(denied)
        self._write_error = write_error
        self.reads: list[tuple[Hive, str]] = []
        self.writes: list[tuple[str, RegValue]] = []

    def values(self, hive: Hive, key: str) -> Sequence[RegValue] | None:
        self.reads.append((hive, key))
        if (hive, key) in self._denied:
            raise RegistryError("access denied")
        return self._keys.get((hive, key))

    def subkeys(self, hive: Hive, key: str) -> Sequence[str] | None:
        self.reads.append((hive, key))
        if (hive, key) in self._denied:
            raise RegistryError("access denied")
        prefix = key + "\\"
        below = [k for h, k in self._keys if h is hive and k.startswith(prefix)]
        if not below and (hive, key) not in self._keys:
            return None
        return list(dict.fromkeys(k.removeprefix(prefix).split("\\")[0] for k in below))

    def set_user_value(self, key: str, value: RegValue) -> None:
        self.writes.append((key, value))
        if self._write_error is not None:
            raise self._write_error
        path, name = (Hive.HKCU, key), value.name.casefold()
        kept = [v for v in self._keys.get(path, ()) if v.name.casefold() != name]
        self._keys[path] = [*kept, value]


def deny_stat(monkeypatch: pytest.MonkeyPatch, denied: Path) -> None:
    """``os.stat`` and ``os.lstat`` of ``denied`` fail with ``EACCES``, as when a directory above
    it cannot be searched; ``chmod`` would deny nothing to root (decision 0011, item 110)."""
    for name in ("stat", "lstat"):
        refuse = functools.partial(_refuse, getattr(os, name), str(denied))
        monkeypatch.setattr(os, name, refuse)


def _refuse(
    real: Callable[..., os.stat_result], denied: str, path: object, *args: object, **kwargs: object
) -> os.stat_result:
    if str(path) == denied:
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), denied)
    return real(path, *args, **kwargs)


def other_device(monkeypatch: pytest.MonkeyPatch, moved: Path) -> None:
    """``os.stat`` and ``os.lstat`` of ``moved`` say it is on another device, as a mount point
    would: a test cannot mount one. Everything else they say is true."""
    for name in ("stat", "lstat"):
        elsewhere = functools.partial(_elsewhere, getattr(os, name), str(moved))
        monkeypatch.setattr(os, name, elsewhere)


_NOT_IN_SEQUENCE = (
    "st_atime",
    "st_mtime",
    "st_ctime",
    "st_atime_ns",
    "st_mtime_ns",
    "st_ctime_ns",
    "st_blksize",
    "st_blocks",
    "st_rdev",
)


def _elsewhere(
    real: Callable[..., os.stat_result], moved: str, path: object, *args: object, **kwargs: object
) -> os.stat_result:
    info = real(path, *args, **kwargs)
    if str(path) != moved:
        return info
    rest = {name: getattr(info, name) for name in _NOT_IN_SEQUENCE}
    return os.stat_result((*info[:2], info.st_dev + 1, *info[3:10]), rest)


def relist(
    monkeypatch: pytest.MonkeyPatch, directory: Path, change: Callable[[list[str]], list[str]]
) -> None:
    """``directory.iterdir()`` gives ``change`` of what it really lists: the same names in another
    order, a name gone by the time it is looked at, or the error ``change`` raises."""
    real = Path.iterdir

    def iterdir(self: Path) -> Iterator[Path]:
        if self != directory:
            yield from real(self)
            return
        for name in change([path.name for path in real(self)]):
            yield self / name

    monkeypatch.setattr(Path, "iterdir", iterdir)


def deny_listing(monkeypatch: pytest.MonkeyPatch, denied: Path) -> None:
    """``denied.iterdir()`` fails with ``EACCES``, as for a directory the user cannot read;
    ``chmod`` would deny nothing to root (decision 0011, item 110)."""

    def refuse(names: list[str]) -> list[str]:
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(denied))

    relist(monkeypatch, denied, refuse)


@contextmanager
def journal_held(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> Iterator[None]:
    """Another program holds the journal for writing (a backup, the sqlite3 shell): safeclean's
    lock does not cover it, so a write in the middle of a command fails, without the wait."""
    db.connect(data_dir / "journal.db").close()  # created and migrated, as by a first command
    monkeypatch.setattr(db, "BUSY_TIMEOUT_MS", 0)
    other = sqlite3.connect(data_dir / "journal.db", isolation_level=None, timeout=0)
    try:
        other.execute("BEGIN IMMEDIATE")
        yield
    finally:
        other.close()
