"""Small text helpers shared by the console commands."""

from __future__ import annotations

_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")


def format_size(size: int) -> str:
    value = float(size)
    index = 0
    while value >= 1024 and index < len(_UNITS) - 1:
        value /= 1024
        index += 1
    return f"{size} B" if index == 0 else f"{value:.1f} {_UNITS[index]}"


def count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
