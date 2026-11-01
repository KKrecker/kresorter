"""Names as organize compares them (decision 0012, item 20).

Two names that differ only in case or in their Unicode normalization are one name to a file
system that ignores case (FAT, exFAT, NTFS, SMB shares, ext4 ``casefold`` directories) and to
the user, and a Mac writes names decomposed. Organize compares folded names on every platform:
a wrong match only keeps a file in place, a missed one moves it away from what expects it.
"""

from __future__ import annotations

import unicodedata


def fold(name: str) -> str:
    """``name`` in NFC, then ``casefold``-ed."""
    return unicodedata.normalize("NFC", name).casefold()
