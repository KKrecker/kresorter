"""Organize's planner: what would move where, and why every other entry stays (decision 0012,
items 1-20). It only looks: ``lstat`` and ``iterdir``; nothing is made, moved or opened.

One level only: the regular files directly in the folder are the candidates, and every entry is
either moved or kept in place with its reason, never skipped in silence. A file is kept by the
first of, in this order: not a regular file, the folder's metadata, work in progress, junk, no
kind in the table, a program next to its libraries, on Windows a new path past the limit, its
category path not a directory, its destination taken. Then companions: a file whose stem (the
name before its first dot) it shares with an entry that would not go to the same category
directory stays too. Names are compared folded (``names``); whether a path is taken is asked of
the file system. The plan is sorted, so it does not depend on the order the folder is listed in.

The limit (decision 0017, item 6) is Windows's without long paths, whether they are enabled or
not: a category directory of at most ``DIRECTORY_LIMIT`` characters and a destination of at most
``PATH_LIMIT``, counted in UTF-16 code units. It is decided from the names alone, before the
category path or the destination is looked at.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from kresorter.core.scanner import ScanContext
from kresorter.organize.categories import default_table
from kresorter.organize.folders import entries
from kresorter.organize.names import first_match, fold

__all__ = ["Move", "Plan", "Stay", "StayReason", "plan"]

METADATA = ("desktop.ini", "thumbs.db")  # with every name that starts with "."
IN_PROGRESS = ("*.part", "*.crdownload", "*.download", "*.partial", "~$*")
LIBRARIES = ("*.dll", "*.so", "*.so.*", "*.dylib")
DIRECTORY_LIMIT = 247  # MAX_PATH less its terminating zero and a directory's 8.3 name
PATH_LIMIT = 259  # MAX_PATH less its terminating zero


class StayReason(StrEnum):
    NOT_REGULAR = "not_regular"
    FOLDER_METADATA = "folder_metadata"
    IN_PROGRESS = "in_progress"
    JUNK = "junk"  # the detail is the junk rule
    UNKNOWN_KIND = "unknown_kind"
    COMPANION = "companion"
    PROGRAM = "program"
    PATH_TOO_LONG = "path_too_long"  # Windows only; the detail says which length passes
    CONFLICT = "conflict"  # the detail says why, when the destination cannot be looked at
    CATEGORY_BLOCKED = "category_blocked"  # likewise for the category path
    MISSING = "missing"  # undo only: nothing at the destination, or nothing it can look at


_RANK = {reason: rank for rank, reason in enumerate(StayReason)}


@dataclass(frozen=True)
class Move:
    """A file to move, with the size and ``mtime_ns`` the plan saw (checked again, item 19)."""

    source: Path
    category: str
    size: int
    mtime_ns: int

    @property
    def destination(self) -> Path:
        return self.source.parent / self.category / self.source.name


@dataclass(frozen=True)
class Stay:
    path: Path
    reason: StayReason
    detail: str = ""


@dataclass(frozen=True)
class Plan:
    folder: Path
    moves: tuple[Move, ...]  # by category in table order, then by name
    stays: tuple[Stay, ...]  # by reason in StayReason order, then by name


def plan(folder: Path, context: ScanContext) -> Plan:
    """The plan for ``folder``. Raises FolderRefused when it is not one organize sorts."""
    found = entries(folder, context)
    table = default_table()
    libraries = any(first_match(name, LIBRARIES) for name in found)
    blocked: dict[str, str | None] = {}
    outcome: dict[str, Move | Stay] = {}
    for name, info in found.items():
        path = folder / name
        stay = _kept(path, info, context)
        kind = None if stay is not None else table.match(name)
        if stay is not None:
            outcome[name] = stay
        elif kind is None:
            outcome[name] = Stay(path, StayReason.UNKNOWN_KIND)
        elif libraries and kind.extension == "exe":
            outcome[name] = Stay(path, StayReason.PROGRAM)
        elif context.platform == "windows" and (long := _too_long(path, kind.category)):
            outcome[name] = Stay(path, StayReason.PATH_TOO_LONG, long)
        else:
            if kind.category not in blocked:
                blocked[kind.category] = _not_a_directory(folder / kind.category)
            outcome[name] = _placed(path, kind.category, info, blocked[kind.category])
    targets: dict[str, set[str | None]] = {}
    for name, planned in outcome.items():
        if not stat.S_ISDIR(found[name].st_mode):
            target = planned.category if isinstance(planned, Move) else None
            targets.setdefault(_stem(name), set()).add(target)
    for name, planned in outcome.items():
        if isinstance(planned, Move) and len(targets[_stem(name)]) > 1:
            outcome[name] = Stay(planned.source, StayReason.COMPANION)
    order = {category: rank for rank, category in enumerate(table.names)}
    moves = [m for m in outcome.values() if isinstance(m, Move)]
    stays = [s for s in outcome.values() if isinstance(s, Stay)]
    return Plan(
        folder,
        tuple(sorted(moves, key=lambda m: (order[m.category], m.source.name))),
        tuple(sorted(stays, key=lambda s: (_RANK[s.reason], s.path.name))),
    )


def _kept(path: Path, info: os.stat_result, context: ScanContext) -> Stay | None:
    """Why ``path`` stays before its kind is asked, or None."""
    if not stat.S_ISREG(info.st_mode):
        return Stay(path, StayReason.NOT_REGULAR)
    if fold(path.name).startswith(".") or first_match(path.name, METADATA):
        return Stay(path, StayReason.FOLDER_METADATA)
    if first_match(path.name, IN_PROGRESS):
        return Stay(path, StayReason.IN_PROGRESS)
    junk = context.classifier.classify(path)
    if junk is not None:
        return Stay(path, StayReason.JUNK, junk.rule_id)
    return None


def _placed(path: Path, category: str, info: os.stat_result, blocked: str | None) -> Move | Stay:
    if blocked is not None:
        return Stay(path, StayReason.CATEGORY_BLOCKED, blocked)
    taken = _taken(path.parent / category / path.name)
    if taken is not None:
        return Stay(path, StayReason.CONFLICT, taken)
    return Move(path, category, info.st_size, info.st_mtime_ns)


def _too_long(path: Path, category: str) -> str | None:
    """Which length of the new path passes Windows's limit, or None."""
    directory = path.parent / category
    length = _length(directory)
    if length > DIRECTORY_LIMIT:
        return f"{directory}: {length} > {DIRECTORY_LIMIT}"
    length = _length(directory / path.name)
    if length > PATH_LIMIT:
        return f"{length} > {PATH_LIMIT}"
    return None


def _length(path: Path) -> int:
    """The length of ``path`` as Windows counts it: UTF-16 code units."""
    return len(str(path).encode("utf-16-le")) // 2


def _not_a_directory(path: Path) -> str | None:
    """None when ``path`` is a directory or nothing; otherwise why its category is blocked."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        return error.strerror or str(error)
    return None if stat.S_ISDIR(info.st_mode) else ""


def _taken(path: Path) -> str | None:
    """None when nothing is at ``path``; otherwise why it counts as taken."""
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        return error.strerror or str(error)
    return ""


def _stem(name: str) -> str:
    return fold(name).split(".")[0]
