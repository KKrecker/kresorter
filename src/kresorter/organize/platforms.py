"""Where organize moves files (decision 0012, items 37-39), and how it renames there (0017).

A blocker is a reason organize does not move files on a system. ``no_open_file_check`` comes
from the open-file checker; ``cloud_sync`` belongs to macOS and is pinned in ``_SYSTEM``, where
Linux and Windows have none (0017, items 1 and 2). Removing one is a decision of its own; the
reasons are in the decisions, not here.

``renamer`` is the rename of every move of organize on a system: forward, back in a rollback
and in an undo batch. On Windows a file another program holds without sharing deletion refuses
to be renamed for a moment (an antivirus, the search indexer, a thumbnail being made), so a
``PermissionError`` is tried again after each of ``DELAYS``.
"""

import os
import time
from collections.abc import Callable, Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from kresorter.core.heuristics import Platform
from kresorter.core.open_files import OpenFileChecker
from kresorter.organize.mover import Rename

__all__ = ["DELAYS", "Blocker", "blockers", "refusal", "renamer"]

DELAYS: tuple[float, ...] = (0.1, 0.2, 0.4, 0.8, 1.6)  # seconds: six tries, 3.1 s of waits


class Blocker(StrEnum):
    NO_OPEN_FILE_CHECK = "no_open_file_check"
    CLOUD_SYNC = "cloud_sync"


_SYSTEM: Mapping[Platform, frozenset[Blocker]] = MappingProxyType(
    {
        "linux": frozenset(),
        "darwin": frozenset({Blocker.CLOUD_SYNC}),
        "windows": frozenset(),
    }
)

_LINE: Mapping[Blocker, str] = MappingProxyType(
    {
        Blocker.NO_OPEN_FILE_CHECK: (
            "no reliable open-file check: a file a program holds open could be moved from under it"
        ),
        Blocker.CLOUD_SYNC: (
            "Desktop and Documents can be synced to the cloud: a move would reach every device"
        ),
    }
)

_NAME: Mapping[Platform, str] = MappingProxyType(
    {"linux": "Linux", "darwin": "macOS", "windows": "Windows"}
)


def blockers(platform: Platform, open_files: OpenFileChecker) -> tuple[Blocker, ...]:
    """What keeps organize from moving files here, in table order; empty means nothing does."""
    found = set(_SYSTEM[platform])
    if not open_files.reliable:
        found.add(Blocker.NO_OPEN_FILE_CHECK)
    return tuple(b for b in Blocker if b in found)


def refusal(platform: Platform, open_files: OpenFileChecker) -> str | None:
    """The message of a blocked system, one line per blocker; ``None`` where nothing blocks."""
    found = blockers(platform, open_files)
    if not found:
        return None
    lines = [f"kresorter: organize does not move files on {_NAME[platform]}; nothing was changed"]
    lines += [f"  - {_LINE[b]}" for b in found]
    return "\n".join(lines) + "\n"


def renamer(
    platform: Platform,
    *,
    rename: Rename = os.rename,
    sleep: Callable[[float], None] = time.sleep,
) -> Rename:
    """Organize's rename on ``platform`` (decision 0017, item 3): ``rename`` itself on Linux and
    macOS, tried once; on Windows tried again after each of ``DELAYS`` while it raises
    ``PermissionError``. Any other error, and the sixth ``PermissionError``, is raised."""
    if platform != "windows":
        return rename

    def patient(source: Path, destination: Path) -> None:
        for delay in DELAYS:
            try:
                rename(source, destination)
            except PermissionError:
                sleep(delay)
            else:
                return
        rename(source, destination)

    return patient
