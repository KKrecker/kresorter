"""A PNG's size, read from its header: no Qt is needed (decision 0015, item 27)."""

from __future__ import annotations

import struct
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(path: Path) -> tuple[int, int]:
    """The width and the height of the PNG at ``path``; ValueError for any other file."""
    head = path.read_bytes()[:24]
    if len(head) < 24 or head[:8] != SIGNATURE or head[12:16] != b"IHDR":
        raise ValueError(f"{path.name}: not a PNG")
    width, height = struct.unpack(">II", head[16:24])
    return width, height
