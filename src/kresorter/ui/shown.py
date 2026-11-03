"""How the window shows a path and a moment (decision 0014, items 48 and 49): a path from the
home folder as ``~``, a moment to the minute in local time."""

from __future__ import annotations

import time
from pathlib import Path

__all__ = ["moment", "shown_path"]


def shown_path(path: Path, home: Path) -> str:
    """``path`` from the home folder, as ``~``; any other path as it is."""
    if path.is_relative_to(home):
        return str(Path("~") / path.relative_to(home))
    return str(path)


def moment(at: float) -> str:
    """``at``, in seconds since the epoch, as the local date and time to the minute."""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(at))
