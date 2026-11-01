"""The folder organize sorts, refused as a whole when it must not be (decision 0012, items 7, 8).

The folder must be a real directory the policy allows, neither the home directory nor above it,
and one that can be listed; and none whose files break when moved: a game library, a project, a
cache or temp directory. What marks the first two lives in ``folders.toml``, read and checked
here; the third is the junk rules' (``JunkClassifier.classify_directory``). Markers are compared
with folded names (``names.first_match``): a wrong match only refuses a folder, a missed one
breaks what is in it.
"""

from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib.resources import files
from pathlib import Path

from safeclean.core.scanner import ScanContext
from safeclean.organize.names import first_match

__all__ = [
    "FolderMarkers",
    "FolderReason",
    "FolderRefused",
    "default_markers",
    "entries",
    "load_markers",
]

_TABLES = {"game_library": ("path_names", "files"), "project": ("version_control", "files")}


class FolderReason(StrEnum):
    NOT_FOUND = "not_found"
    NOT_A_DIRECTORY = "not_a_directory"
    LINK = "link"  # the folder, or a directory above it; the detail is where it leads
    BLOCKED = "blocked"  # by the policy; the detail is its BlockReason
    HOME = "home"  # the home directory or a directory above it
    UNREADABLE = "unreadable"  # the folder or an entry cannot be looked at; the detail says why
    GAME_LIBRARY = "game_library"  # the detail is the marker
    PROJECT = "project"  # the detail is the marker
    CACHE_OR_TEMP = "cache_or_temp"  # the detail is the junk rule


class FolderRefused(Exception):
    """The folder is not one organize sorts: nothing is planned."""

    def __init__(self, folder: Path, reason: FolderReason, detail: str = "") -> None:
        super().__init__(folder, reason, detail)
        self.folder = folder
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class FolderMarkers:
    game_path_names: tuple[str, ...]  # a name among the folder's path names
    game_files: tuple[str, ...]  # an entry of the folder
    version_control: tuple[str, ...]  # a directory in the folder or above it, by name
    project_files: tuple[str, ...]  # an entry of the folder


def load_markers(text: str) -> FolderMarkers:
    """Parse and check the markers from TOML text. Raises ValueError naming what is wrong."""
    data = tomllib.loads(text)
    if sorted(data) != sorted(_TABLES):
        raise ValueError("the tables [game_library] and [project] are expected, nothing else")
    lists: list[tuple[str, ...]] = []
    for table, keys in _TABLES.items():
        entries = data[table]
        if not isinstance(entries, dict) or sorted(entries) != sorted(keys):
            raise ValueError(f"[{table}]: {', '.join(keys)} are expected, nothing else")
        for key in keys:
            names = entries[key]
            if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
                raise ValueError(f"[{table}] {key}: a list of names is expected")
            lists.append(tuple(names))
    return FolderMarkers(*lists)


@cache
def default_markers() -> FolderMarkers:
    """The markers shipped with safeclean (``safeclean/organize/folders.toml``)."""
    data = files("safeclean.organize").joinpath("folders.toml").read_text(encoding="utf-8")
    return load_markers(data)


def entries(folder: Path, context: ScanContext) -> dict[str, os.stat_result]:
    """The entries of ``folder`` by name, each as ``lstat`` saw it, once ``folder`` is one
    organize sorts. Raises FolderRefused otherwise, ValueError for a relative ``folder``."""
    markers = default_markers()
    _check_path(folder, context, markers)
    found = _list(folder)
    for name in sorted(found):
        for reason, patterns in (
            (FolderReason.GAME_LIBRARY, markers.game_files),
            (FolderReason.PROJECT, markers.project_files),
        ):
            marker = first_match(name, patterns)
            if marker is not None:
                raise FolderRefused(folder, reason, marker)
    return found


def _check_path(folder: Path, context: ScanContext, markers: FolderMarkers) -> None:
    verdict = context.policy.check_path(folder)
    if not verdict.allowed:
        raise FolderRefused(folder, FolderReason.BLOCKED, f"{verdict.reason}")
    if context.policy.holds_home(folder):
        raise FolderRefused(folder, FolderReason.HOME)
    try:
        info = folder.lstat()
    except (FileNotFoundError, NotADirectoryError):
        raise FolderRefused(folder, FolderReason.NOT_FOUND) from None
    except OSError as error:
        raise FolderRefused(folder, FolderReason.UNREADABLE, _why(error)) from None
    real = os.path.realpath(folder)
    if stat.S_ISLNK(info.st_mode) or real != os.fspath(folder):
        raise FolderRefused(folder, FolderReason.LINK, real)
    if not stat.S_ISDIR(info.st_mode):
        raise FolderRefused(folder, FolderReason.NOT_A_DIRECTORY)
    junk = context.classifier.classify_directory(folder)
    if junk is not None:
        raise FolderRefused(folder, FolderReason.CACHE_OR_TEMP, junk.rule_id)
    for part in folder.parts[1:]:
        marker = first_match(part, markers.game_path_names)
        if marker is not None:
            raise FolderRefused(folder, FolderReason.GAME_LIBRARY, marker)
    for directory in (folder, *folder.parents):
        for name in markers.version_control:
            if os.path.lexists(directory / name):
                raise FolderRefused(folder, FolderReason.PROJECT, name)


def _list(folder: Path) -> dict[str, os.stat_result]:
    try:
        names = [path.name for path in folder.iterdir()]
    except OSError as error:
        raise FolderRefused(folder, FolderReason.UNREADABLE, _why(error)) from None
    found: dict[str, os.stat_result] = {}
    for name in names:
        try:
            found[name] = (folder / name).lstat()
        except FileNotFoundError:
            continue  # gone since the listing: no longer in the folder
        except OSError as error:
            detail = f"{name}: {_why(error)}"
            raise FolderRefused(folder, FolderReason.UNREADABLE, detail) from None
    return found


def _why(error: OSError) -> str:
    return error.strerror or str(error)
