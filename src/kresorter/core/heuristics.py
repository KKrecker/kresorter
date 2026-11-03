"""Junk heuristics: classify a path as junk using rules loaded from data (TOML).

The engine only interprets rules; what counts as junk lives in ``junk_rules.toml``.
A match is a *candidate*, not a decision: safety (policy, open files) and the later
"safe to delete" score are separate concerns.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatchcase
from functools import cache
from importlib.resources import files
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from typing import Any, Literal, get_args

Platform = Literal["windows", "linux", "darwin"]
PLATFORMS: frozenset[str] = frozenset(get_args(Platform))
_REQUIRED = ("id", "category", "description")
_OPTIONAL = ("dirs", "files", "platforms")


class JunkCategory(StrEnum):
    CACHE = "cache"
    TEMP = "temp"
    THUMBNAILS = "thumbnails"
    CRASH_DUMP = "crash_dump"
    OS_METADATA = "os_metadata"


@dataclass(frozen=True)
class DirPattern:
    segments: tuple[str, ...]
    anchored: bool


@dataclass(frozen=True)
class JunkRule:
    id: str
    category: JunkCategory
    description: str
    dirs: tuple[DirPattern, ...]
    files: tuple[str, ...]
    platforms: frozenset[str]


@dataclass(frozen=True)
class JunkMatch:
    path: PurePath
    rule_id: str
    category: JunkCategory
    description: str


# --- loading and validation ----------------------------------------------------------------------


def load_rules(text: str) -> tuple[JunkRule, ...]:
    """Parse and validate rules from TOML text. Raises ValueError with the offending rule."""
    tables = tomllib.loads(text).get("rule")
    if not isinstance(tables, list):
        raise ValueError("expected [[rule]] tables")
    rules = tuple(_parse_rule(i, table) for i, table in enumerate(tables, start=1))
    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            raise ValueError(f"duplicate rule id {rule.id!r}")
        seen.add(rule.id)
    return rules


@cache
def default_rules() -> tuple[JunkRule, ...]:
    """Rules shipped with kresorter (``kresorter/core/junk_rules.toml``)."""
    data = files("kresorter.core").joinpath("junk_rules.toml").read_text(encoding="utf-8")
    return load_rules(data)


def _parse_rule(index: int, table: Mapping[str, Any]) -> JunkRule:
    for key in _REQUIRED:
        if not isinstance(table.get(key), str):
            raise ValueError(f"rule #{index}: missing required key {key!r}")
    where = f"rule {table['id']!r}"
    unknown = set(table) - set(_REQUIRED) - set(_OPTIONAL)
    if unknown:
        raise ValueError(f"{where}: unknown key {sorted(unknown)[0]!r}")
    try:
        category = JunkCategory(table["category"])
    except ValueError:
        raise ValueError(f"{where}: unknown category {table['category']!r}") from None
    dirs = tuple(_parse_dir(where, p) for p in _strings(where, table, "dirs"))
    file_globs = tuple(_parse_file(where, p) for p in _strings(where, table, "files"))
    if not dirs and not file_globs:
        raise ValueError(f"{where}: needs dirs or files")
    return JunkRule(
        id=table["id"],
        category=category,
        description=table["description"],
        dirs=dirs,
        files=file_globs,
        platforms=_parse_platforms(where, table),
    )


def _strings(where: str, table: Mapping[str, Any], key: str) -> list[str]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{where}: {key!r} must be a list of strings")
    return [str(v) for v in value]


def _parse_dir(where: str, pattern: str) -> DirPattern:
    anchored = pattern.startswith("/")
    segments = tuple((pattern[1:] if anchored else pattern).split("/"))
    if "" in segments:
        raise ValueError(f"{where}: empty segment in {pattern!r}")
    if ".." in segments:
        raise ValueError(f"{where}: '..' is not allowed in {pattern!r}")
    return DirPattern(segments=segments, anchored=anchored)


def _parse_file(where: str, pattern: str) -> str:
    if "/" in pattern or "\\" in pattern or not pattern:
        raise ValueError(f"{where}: file pattern must be a bare name glob, got {pattern!r}")
    return pattern


def _parse_platforms(where: str, table: Mapping[str, Any]) -> frozenset[str]:
    if "platforms" not in table:
        return PLATFORMS
    platforms = frozenset(_strings(where, table, "platforms"))
    unknown = platforms - PLATFORMS
    if unknown:
        raise ValueError(f"{where}: unknown platform {sorted(unknown)[0]!r}")
    return platforms


# --- matching ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Compiled:
    rule: JunkRule
    dirs: tuple[DirPattern, ...]
    files: tuple[str, ...]


def _dirs_match(dirs: tuple[str, ...], pattern: DirPattern) -> bool:
    size = len(pattern.segments)
    last_start = len(dirs) - size + 1
    starts = range(min(1, last_start)) if pattern.anchored else range(last_start)
    return any(
        all(fnmatchcase(dirs[i + j], seg) for j, seg in enumerate(pattern.segments)) for i in starts
    )


def _matches(rule: _Compiled, dirs: tuple[str, ...], name: str) -> bool:
    dirs_ok = not rule.dirs or any(_dirs_match(dirs, p) for p in rule.dirs)
    files_ok = not rule.files or any(fnmatchcase(name, f) for f in rule.files)
    return dirs_ok and files_ok


class JunkClassifier:
    """Applies rules for one platform. Case-insensitive on Windows and macOS."""

    def __init__(self, rules: Iterable[JunkRule], *, platform: Platform) -> None:
        self._flavor: type[PurePath] = PureWindowsPath if platform == "windows" else PurePosixPath
        fold: Callable[[str], str] = str if platform == "linux" else str.casefold
        self._fold = fold
        self._rules = tuple(
            _Compiled(
                rule=rule,
                dirs=tuple(
                    DirPattern(tuple(fold(s) for s in p.segments), p.anchored) for p in rule.dirs
                ),
                files=tuple(fold(f) for f in rule.files),
            )
            for rule in rules
            if platform in rule.platforms
        )

    def classify(self, path: PurePath) -> JunkMatch | None:
        """Return the first matching rule for ``path`` (absolute), or None."""
        pure = self._flavor(path)
        if not pure.is_absolute():
            raise ValueError(f"path must be absolute: {path}")
        parts = tuple(self._fold(p) for p in pure.parts[1:])
        if not parts:
            return None
        dirs, name = parts[:-1], parts[-1]
        for compiled in self._rules:
            if _matches(compiled, dirs, name):
                rule = compiled.rule
                return JunkMatch(path, rule.id, rule.category, rule.description)
        return None

    def classify_directory(self, path: PurePath) -> JunkMatch | None:
        """Return the first rule whose directories match ``path`` (absolute) or a directory above
        it, or None. Files are not looked at: a rule that names files too matches the directory
        it looks in, and a rule of file names alone matches no directory (decision 0012, item 8)."""
        pure = self._flavor(path)
        if not pure.is_absolute():
            raise ValueError(f"path must be absolute: {path}")
        dirs = tuple(self._fold(p) for p in pure.parts[1:])
        for compiled in self._rules:
            if any(_dirs_match(dirs, pattern) for pattern in compiled.dirs):
                rule = compiled.rule
                return JunkMatch(path, rule.id, rule.category, rule.description)
        return None
