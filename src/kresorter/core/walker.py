"""Safe directory traversal.

* Never follows symlinks or Windows junctions; they are reported as skipped.
* User-chosen roots are resolved first, then checked against the policy like everything else.
* Blacklisted directories are pruned without being listed.
* Every skip is reported with a reason; an error in one directory does not stop the walk.
* Iterative (no recursion limit on deep trees), deterministic order (sorted by name).
* A directory's files are checked by the policy by name, then for being open: side by side
  with the share-mode check, their events in their order all the same (decision 0018).
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from kresorter.core.models import FileEntry, Skipped, SkipReason, skipped_from_os_error
from kresorter.core.open_files import OpenFileChecker, threads_for
from kresorter.core.policy import PathPolicy, Verdict, check_open

Event = FileEntry | Skipped


def walk(roots: Iterable[Path], policy: PathPolicy, open_files: OpenFileChecker) -> Iterator[Event]:
    """Yield a FileEntry for every allowed regular file under ``roots``, Skipped for the rest."""
    threads = threads_for(open_files)
    with ExitStack() as stack:
        pool = stack.enter_context(ThreadPoolExecutor(threads)) if threads > 1 else None
        walker = _Walker(policy, open_files, pool)
        for root in roots:
            yield from walker.walk_root(Path(root))


@dataclass(frozen=True)
class _Allowed:
    """A regular file the policy allows, its open-file check still to come."""

    path: Path
    info: os.stat_result


def _is_link(entry: os.DirEntry[str]) -> bool:
    is_junction: Callable[[], bool] | None = getattr(entry, "is_junction", None)
    return entry.is_symlink() or (is_junction is not None and is_junction())


class _Walker:
    def __init__(
        self, policy: PathPolicy, open_files: OpenFileChecker, pool: ThreadPoolExecutor | None
    ) -> None:
        self._policy = policy
        self._open_files = open_files
        self._pool = pool
        self._seen_dirs: set[Path] = set()

    def walk_root(self, root: Path) -> Iterator[Event]:
        try:
            resolved = root.resolve(strict=True)
        except OSError as error:
            yield skipped_from_os_error(root, error)
            return
        if resolved.is_dir():
            yield from self._walk_dir(resolved)
        elif not self._already_walked(resolved):
            found = self._file(resolved, resolved.stat, partial(self._policy.check_path, resolved))
            yield from self._checked([found])

    def _already_walked(self, path: Path) -> bool:
        return any(parent in self._seen_dirs for parent in path.parents)

    def _walk_dir(self, start: Path) -> Iterator[Event]:
        stack = [start]
        while stack:
            directory = stack.pop()
            if directory in self._seen_dirs:
                continue
            verdict = self._policy.check_path(directory)
            if not verdict.allowed:
                yield Skipped(directory, SkipReason.BLOCKED, block_reason=verdict.reason)
                continue
            self._seen_dirs.add(directory)
            subdirs: list[Path] = []
            yield from self._list_dir(directory, subdirs)
            stack.extend(reversed(subdirs))

    def _list_dir(self, directory: Path, subdirs: list[Path]) -> Iterator[Event]:
        try:
            with os.scandir(directory) as listing:
                entries = sorted(listing, key=lambda e: e.name)
        except OSError as error:
            yield skipped_from_os_error(directory, error)
            return
        names = self._policy.in_directory(directory)  # its files by name (decision 0018, 14)
        found: list[Event | _Allowed] = []
        for entry in entries:
            path = Path(entry.path)
            if _is_link(entry):
                found.append(Skipped(path=path, reason=SkipReason.SYMLINK))
            elif entry.is_dir(follow_symlinks=False):
                subdirs.append(path)
            else:
                get_stat = partial(entry.stat, follow_symlinks=False)
                found.append(self._file(path, get_stat, partial(names.check_name, entry.name)))
        yield from self._checked(found)

    def _file(
        self, path: Path, get_stat: Callable[[], os.stat_result], check: Callable[[], Verdict]
    ) -> Event | _Allowed:
        try:
            info = get_stat()
        except OSError as error:
            return skipped_from_os_error(path, error)
        if not stat.S_ISREG(info.st_mode):
            return Skipped(path=path, reason=SkipReason.SPECIAL)
        verdict = check()
        if not verdict.allowed:
            return Skipped(path=path, reason=SkipReason.BLOCKED, block_reason=verdict.reason)
        return _Allowed(path, info)

    def _checked(self, found: list[Event | _Allowed]) -> Iterator[Event]:
        """``found`` in its order, each allowed file checked for being open: side by side in
        the pool when there is one (decision 0018, item 12), each answer its own."""
        allowed = [one.path for one in found if isinstance(one, _Allowed)]
        check = partial(check_open, open_files=self._open_files)
        pool = self._pool
        answers = iter(
            pool.map(check, allowed) if pool and len(allowed) > 1 else map(check, allowed)
        )
        for one in found:
            if not isinstance(one, _Allowed):
                yield one
                continue
            verdict = next(answers)
            if verdict.allowed:
                yield FileEntry(path=one.path, size=one.info.st_size, mtime_ns=one.info.st_mtime_ns)
            else:
                yield Skipped(path=one.path, reason=SkipReason.BLOCKED, block_reason=verdict.reason)
