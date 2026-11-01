"""Which copy of a duplicate group stays, and why (decision 0010).

Pure: decides on scanned entries and reads nothing from disk. The keeper is the minimum of a
fixed key (not junk, outside the safe zones, oldest ``mtime_ns``, shallowest, path order); the
reason is the first key component that separates it from the runner-up. Every other copy
becomes a quarantine ``Candidate`` twinned with the keeper, so preflight re-checks the keeper
right before anything moves. A group never loses all its copies.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath

from safeclean.core.heuristics import JunkClassifier
from safeclean.core.models import FileEntry
from safeclean.core.preflight import Candidate


class KeepReason(StrEnum):
    """The first criterion that put the keeper ahead of the runner-up."""

    NOT_JUNK = "not_junk"
    OUTSIDE_SAFE_ZONE = "outside_safe_zone"
    OLDEST = "oldest"
    SHALLOWEST = "shallowest"
    FIRST_BY_PATH = "first_by_path"


# Same order as the components of the ranking key in ``decide``.
_ORDER = tuple(KeepReason)


@dataclass(frozen=True)
class DuplicateDecision:
    digest: str
    keep: FileEntry
    reason: KeepReason
    remove: tuple[Candidate, ...]

    @property
    def wasted_bytes(self) -> int:
        return self.keep.size * len(self.remove)


def decide(
    digest: str,
    copies: Sequence[FileEntry],
    *,
    classifier: JunkClassifier,
    safe_zones: Sequence[PurePath],
) -> DuplicateDecision:
    if len(copies) < 2:
        raise ValueError("a duplicate group needs at least two copies")
    if len({c.size for c in copies}) != 1:
        raise ValueError("copies in a duplicate group must have the same size")
    if len({c.path for c in copies}) != len(copies):
        raise ValueError("the same path appears twice in a duplicate group")

    def key(entry: FileEntry) -> tuple[bool, bool, int, int, str]:
        return (
            classifier.classify(entry.path) is not None,
            any(entry.path.is_relative_to(zone) for zone in safe_zones),
            entry.mtime_ns,
            len(entry.path.parts),
            str(entry.path),
        )

    ranked = sorted(copies, key=key)
    keeper, runner_up = ranked[0], ranked[1]
    pairs = zip(_ORDER, key(keeper), key(runner_up), strict=True)
    reason = next(r for r, ours, theirs in pairs if ours != theirs)  # paths are unique
    remove = tuple(Candidate(entry=c, twin=keeper, digest=digest) for c in ranked[1:])
    return DuplicateDecision(digest, keeper, reason, remove)
