"""Where organize moves files (decision 0012, items 37-39).

A blocker is a reason organize does not move files on a system. ``no_open_file_check`` comes
from the open-file checker; the others belong to the system and are pinned in ``_SYSTEM``.
Removing one is a decision of its own; the reasons are in the decision, not here.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from kresorter.core.heuristics import Platform
from kresorter.core.open_files import OpenFileChecker

__all__ = ["Blocker", "blockers", "refusal"]


class Blocker(StrEnum):
    NO_OPEN_FILE_CHECK = "no_open_file_check"
    SHARING_VIOLATIONS = "sharing_violations"
    PATH_LENGTH_LIMIT = "path_length_limit"
    CLOUD_SYNC = "cloud_sync"


_SYSTEM: Mapping[Platform, frozenset[Blocker]] = MappingProxyType(
    {
        "linux": frozenset(),
        "darwin": frozenset({Blocker.CLOUD_SYNC}),
        "windows": frozenset(
            {Blocker.SHARING_VIOLATIONS, Blocker.PATH_LENGTH_LIMIT, Blocker.CLOUD_SYNC}
        ),
    }
)

_LINE: Mapping[Blocker, str] = MappingProxyType(
    {
        Blocker.NO_OPEN_FILE_CHECK: (
            "no reliable open-file check: a file a program holds open could be moved from under it"
        ),
        Blocker.SHARING_VIOLATIONS: (
            "a file another program holds open can refuse to move halfway through a batch,"
            " and so can the move back"
        ),
        Blocker.PATH_LENGTH_LIMIT: "one directory deeper, a path can pass the 260-character limit",
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
