"""Names as organize compares them (decision 0012, item 20).

Two names that differ only in case or in their Unicode normalization are one name to a file
system that ignores case (FAT, exFAT, NTFS, SMB shares, ext4 ``casefold`` directories) and to
the user, and a Mac writes names decomposed. Organize compares folded names on every platform:
a wrong match only keeps a file in place, a missed one moves it away from what expects it.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from fnmatch import fnmatchcase


def fold(name: str) -> str:
    """``name`` in NFC, then ``casefold``-ed."""
    return unicodedata.normalize("NFC", name).casefold()


def first_match(name: str, patterns: Iterable[str]) -> str | None:
    """The first of ``patterns`` (``fnmatch``, as written) that ``name`` matches, both folded."""
    folded = fold(name)
    return next((pattern for pattern in patterns if fnmatchcase(folded, fold(pattern))), None)


LONGEST_FOLDER = 40
_SIGNS = frozenset(" -_.,()&'")
_DEVICES = frozenset(
    {"con", "prn", "aux", "nul", *(f"{port}{n}" for port in ("com", "lpt") for n in range(1, 10))}
)


def is_folder_name(name: str) -> bool:
    """A portable single folder name accepted for proposed groups."""
    if not 1 <= len(name) <= LONGEST_FOLDER or name[-1] in " .":
        return False
    if not all(_allowed(character) for character in name) or name[0] in _SIGNS:
        return False
    return fold(name.split(".")[0]) not in _DEVICES


def _allowed(character: str) -> bool:
    return character.isalpha() or character.isdecimal() or character in _SIGNS
