"""Safe directory traversal.

* Never follows symlinks or Windows junctions; they are reported as skipped.
* User-chosen roots are resolved first, then checked against the policy like everything else.
* Blacklisted directories are pruned without being listed.
* Every skip is reported with a reason; an error in one directory does not stop the walk.
* Iterative (no recursion limit on deep trees), deterministic order (sorted by name).
* A directory's files are checked by the policy by name (decision 0018, item 14).
* It lists without opening any file: the scan asks about the files whose being open decides
  something once they are known (decision 0020, item 17).
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterable, Iterator
from functools import partial
from pathlib import Path

from kresorter.core.models import FileEntry, Skipped, SkipReason, skipped_from_os_error
from kresorter.core.policy import PathPolicy, Verdict

Event = FileEntry | Skipped


def walk(roots: Iterable[Path], policy: PathPolicy) -> Iterator[Event]:
    """Yield a FileEntry for every allowed regular file under ``roots``, Skipped for the rest."""
    walker = _Walker(policy)
    for root in roots:
        yield from walker.walk_root(Path(root))


def _is_link(entry: os.DirEntry[str]) -> bool:
    is_junction: Callable[[], bool] | None = getattr(entry, "is_junction", None)
    return entry.is_symlink() or (is_junction is not None and is_junction())


class _Walker:
    def __init__(self, policy: PathPolicy) -> None:
        self._policy = policy
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
            yield self._file(resolved, resolved.stat, partial(self._policy.check_path, resolved))

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
        for entry in entries:
            path = Path(entry.path)
            if _is_link(entry):
                yield Skipped(path=path, reason=SkipReason.SYMLINK)
            elif entry.is_dir(follow_symlinks=False):
                subdirs.append(path)
            else:
                get_stat = partial(entry.stat, follow_symlinks=False)
                yield self._file(path, get_stat, partial(names.check_name, entry.name))

    def _file(
        self, path: Path, get_stat: Callable[[], os.stat_result], check: Callable[[], Verdict]
    ) -> Event:
        try:
            info = get_stat()
        except OSError as error:
            return skipped_from_os_error(path, error)
        if not stat.S_ISREG(info.st_mode):
            return Skipped(path=path, reason=SkipReason.SPECIAL)
        verdict = check()
        if not verdict.allowed:
            return Skipped(path=path, reason=SkipReason.BLOCKED, block_reason=verdict.reason)
        return FileEntry(path=path, size=info.st_size, mtime_ns=info.st_mtime_ns)
