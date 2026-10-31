"""Small text helpers shared by the console commands."""

from __future__ import annotations

from typing import Any

from safeclean.core.models import Skipped

OPEN_FILES_NOTE = (
    "Note: open-file check is not available yet; files will be re-checked before any action."
)

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


def skip_line(item: Skipped) -> str:
    label = f"{item.reason} ({item.block_reason})" if item.block_reason else str(item.reason)
    detail = f" ({item.detail})" if item.detail else ""
    return f"  {label}: {item.path}{detail}"


def skip_json(item: Skipped) -> dict[str, Any]:
    return {
        "path": str(item.path),
        "reason": str(item.reason),
        "block_reason": str(item.block_reason) if item.block_reason else None,
        "detail": item.detail,
    }
