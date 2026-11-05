"""Sessions: what keeps a sign-in, a saved password or the open tabs (decision 0020, item 13).

What they are lives in ``sessions.toml``; this module reads it and tells, by a path's names
alone, whether it is one or inside one. The policy blocks them (``BlockReason.SESSION``).
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cache, partial
from importlib.resources import files
from typing import Any

__all__ = ["Session", "SessionPaths", "default_sessions", "load_sessions", "session_patterns"]

Names = tuple[str, ...]
Match = Callable[[str], bool]
_TEXTS = ("id", "what")
_LISTS = ("paths", "under")
_GLOB = "*?["


@dataclass(frozen=True)
class Session:
    id: str
    what: str
    under: tuple[str, ...]
    paths: tuple[str, ...]

    @property
    def patterns(self) -> tuple[str, ...]:
        """Its paths, each joined under each of its ``under`` when it has them."""
        if not self.under:
            return self.paths
        return tuple(f"{under}/{path}" for under in self.under for path in self.paths)


# --- loading and checking ------------------------------------------------------------------------


def load_sessions(text: str) -> tuple[Session, ...]:
    """Parse and check sessions from TOML text. Raises ValueError naming what is wrong."""
    tables = tomllib.loads(text).get("session")
    if not isinstance(tables, list):
        raise ValueError("expected [[session]] tables")
    sessions = tuple(_parse(index, table) for index, table in enumerate(tables, start=1))
    seen: set[str] = set()
    for session in sessions:
        if session.id in seen:
            raise ValueError(f"duplicate session id {session.id!r}")
        seen.add(session.id)
    return sessions


@cache
def default_sessions() -> tuple[Session, ...]:
    """The sessions shipped with kresorter (``kresorter/core/sessions.toml``)."""
    data = files("kresorter.core").joinpath("sessions.toml").read_text(encoding="utf-8")
    return load_sessions(data)


def session_patterns() -> tuple[str, ...]:
    """The patterns of every session shipped, for every system (a copy of a profile on another
    disk keeps its sign-ins too)."""
    return tuple(pattern for session in default_sessions() for pattern in session.patterns)


def _parse(index: int, table: Mapping[str, Any]) -> Session:
    for key in _TEXTS:
        if not isinstance(table.get(key), str):
            raise ValueError(f"session #{index}: missing required key {key!r}")
    where = f"session {table['id']!r}"
    unknown = set(table) - set(_TEXTS) - set(_LISTS)
    if unknown:
        raise ValueError(f"{where}: unknown key {sorted(unknown)[0]!r}")
    paths = _strings(where, table, "paths")
    if not paths:
        raise ValueError(f"{where}: needs paths")
    under = _strings(where, table, "under")
    session = Session(table["id"], table["what"], under, paths)
    for pattern in (*under, *paths):
        _check_names(where, pattern)
    for pattern in session.patterns:
        if _written(tuple(pattern.split("/"))) is None:
            raise ValueError(f"{where}: {pattern!r} writes out no name in full")
    return session


def _strings(where: str, table: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{where}: {key!r} must be a list of strings")
    return tuple(value)


def _check_names(where: str, pattern: str) -> None:
    for name in pattern.split("/"):
        if name in ("", ".", "..") or "\\" in name:
            raise ValueError(f"{where}: {pattern!r} is no names one inside the other")


# --- matching ------------------------------------------------------------------------------------


def _written(names: Names) -> tuple[int, str] | None:
    """The last of ``names`` written out in full, and how far it is from their end."""
    return next(
        (
            (offset, name)
            for offset, name in enumerate(reversed(names))
            if not any(c in name for c in _GLOB)
        ),
        None,
    )


def _matcher(name: str) -> Match:
    """A glob, or a name compared by equality."""
    if any(c in name for c in _GLOB):
        return partial(fnmatchcase, pat=name)
    return name.__eq__


@dataclass(frozen=True)
class _Pattern:
    head: tuple[Match, ...]  # the names before its last
    last: Match

    def follows(self, names: Names) -> bool:
        """True when ``names`` end with the pattern's names before its last."""
        start = len(names) - len(self.head)
        return start >= 0 and all(match(names[start + i]) for i, match in enumerate(self.head))


class SessionPaths:
    """Patterns of sessions, folded as a system folds its names, asked of a path's names
    (folded the same way, the anchor left out). A pattern is found by the last of its names
    written out in full, and how far it is from the pattern's end, so a path's names are
    looked up rather than every pattern tried on them."""

    def __init__(self, patterns: Iterable[str], fold: Callable[[str], str]) -> None:
        by_offset: dict[int, dict[str, list[_Pattern]]] = {}
        for pattern in patterns:
            names = tuple(fold(name) for name in pattern.split("/"))
            written = _written(names)
            if written is None:
                raise ValueError(f"{pattern!r} writes out no name in full")
            offset, name = written
            compiled = _Pattern(tuple(map(_matcher, names[:-1])), _matcher(names[-1]))
            by_offset.setdefault(offset, {}).setdefault(name, []).append(compiled)
        self._by_offset = tuple(
            (offset, {name: tuple(found) for name, found in by_name.items()})
            for offset, by_name in sorted(by_offset.items())
        )

    def holds(self, names: Names) -> bool:
        """True when ``names`` are a session's, or inside one."""
        return any(self._ends(names[:end]) for end in range(1, len(names) + 1))

    def names_in(self, directory: Names) -> Callable[[str], bool]:
        """Whether a name in ``directory`` is a session's, as ``holds`` would say of its names
        if ``directory`` is not held: the patterns found once for the directory, but those
        whose last name is the one written out, found by the name."""
        lasts: list[Match] = []
        named: Mapping[str, tuple[_Pattern, ...]] = {}
        for offset, by_name in self._by_offset:
            if offset == 0:
                named = by_name
            elif offset <= len(directory):
                found = by_name.get(directory[-offset], ())
                lasts.extend(p.last for p in found if p.follows(directory))

        def ends(name: str) -> bool:
            return any(last(name) for last in lasts) or any(
                p.follows(directory) for p in named.get(name, ())
            )

        return ends

    def _ends(self, names: Names) -> bool:
        for offset, by_name in self._by_offset:
            if offset >= len(names):
                break
            for pattern in by_name.get(names[-1 - offset], ()):
                if pattern.last(names[-1]) and pattern.follows(names[:-1]):
                    return True
        return False
