"""Bounded, never-blocking reading of autostart entry files, shared by the readers (0011)."""

from __future__ import annotations

import stat
from collections.abc import Mapping
from pathlib import Path

MAX_ENTRY_BYTES = 64 * 1024


class BrokenEntryError(Exception):
    """The entry cannot be used; the message is the user-facing reason it is skipped."""


def read_entry(path: Path) -> bytes:
    """The bytes of a regular file of at most ``MAX_ENTRY_BYTES``, following links.

    Anything else (missing, a directory, a FIFO that would block, too large) is a
    ``BrokenEntryError``; only regular files are ever opened.
    """
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise BrokenEntryError("not a regular file")
        if info.st_size > MAX_ENTRY_BYTES:
            raise BrokenEntryError(f"larger than {MAX_ENTRY_BYTES} bytes")
        with path.open("rb") as handle:
            return handle.read(MAX_ENTRY_BYTES + 1)
    except OSError as error:
        raise BrokenEntryError(f"cannot read: {error.strerror}") from None


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise BrokenEntryError("not UTF-8") from None


def config_home(env: Mapping[str, str], home: Path) -> Path:
    """``$XDG_CONFIG_HOME`` if absolute, else ``~/.config`` (XDG Base Directory spec)."""
    value = Path(env.get("XDG_CONFIG_HOME") or ".")
    return value if value.is_absolute() else home / ".config"
