"""Files for tests to act on: written, and snapshotted to show that nothing changed."""

from __future__ import annotations

import os
import time
from pathlib import Path


def write(path: Path, data: bytes = b"payload") -> Path:
    """``data`` at ``path``; missing parent directories are made first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def write_desktop(directory: Path, name: str, raw: bytes) -> Path:
    """The XDG entry ``<directory>/<name>.desktop``, holding ``raw``."""
    return write(directory / f"{name}.desktop", raw)


def snapshot(root: Path) -> list[tuple[str, int, int, bytes]]:
    """Every file under ``root``, sorted: path, size, ``mtime_ns``, bytes. Equal before and after
    a command that must change nothing."""
    return sorted(
        (str(p), p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes())
        for p in root.rglob("*")
        if p.is_file()
    )


DAY_NS = 86_400 * 1_000_000_000


def aged(path: Path, days: int) -> Path:
    """``path`` last modified ``days`` days ago."""
    stamp = time.time_ns() - days * DAY_NS
    os.utime(path, ns=(stamp, stamp))
    return path
