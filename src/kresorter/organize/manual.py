"""Read-only plans for manually assigned files.

This is groundwork, not an execution API: directory moves and the manual UI are not yet
implemented. The existing organizer's checks still apply. Unassigned companions stay beside
assigned files, so assigning one does not implicitly move the other.
"""

from __future__ import annotations

import stat
from collections.abc import Mapping
from pathlib import Path

from kresorter.core.scanner import ScanContext
from kresorter.organize.names import fold, is_folder_name
from kresorter.organize.planner import Plan, Stay, StayReason, plan

__all__ = ["plan_manual"]


def plan_manual(folder: Path, context: ScanContext, assignments: Mapping[str, str]) -> Plan:
    """Plan only explicitly assigned names, without making directories or moving anything.

    Group names use the same safe name rules as AI groups. Missing names and invalid group
    names are rejected rather than silently reinterpreted. A directory remains a non-regular
    item; this function does not grant permission to move one.
    """
    if any(not is_folder_name(group) for group in assignments.values()):
        raise ValueError("invalid group name")
    found = plan(folder, context, assignments)
    paths = {move.source.name: move.source for move in found.moves}
    paths.update({stay.path.name: stay.path for stay in found.stays})
    if not assignments.keys() <= paths.keys():
        raise ValueError("an assigned name is not in the folder")
    unassigned_stems = {
        _stem(name)
        for name, path in paths.items()
        if name not in assignments and _is_companion(path)
    }
    moves = []
    stays = [stay for stay in found.stays if stay.path.name in assignments]
    for move in found.moves:
        if move.source.name not in assignments:
            continue
        if _stem(move.source.name) in unassigned_stems:
            stays.append(Stay(move.source, StayReason.COMPANION))
        else:
            moves.append(move)
    stays.sort(key=lambda stay: (list(StayReason).index(stay.reason), stay.path.name))
    return Plan(found.folder, tuple(moves), tuple(stays))


def _stem(name: str) -> str:
    return fold(name).split(".")[0]


def _is_companion(path: Path) -> bool:
    try:
        return not stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return True  # uncertainty must not allow a file to move away from its companion
