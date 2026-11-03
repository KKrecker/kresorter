"""What changes autostart entries on a platform, for the CLI and the window (decision 0014,
item 12): XDG entries on Linux, HKCU Run values on Windows, nothing on macOS (0011)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from kresorter.autostart.changes import AutostartStore, XdgChanges
from kresorter.autostart.listing import AutostartContext
from kresorter.autostart.run_changes import RunKeyChanges
from kresorter.autostart.xdg import autostart_dirs

__all__ = ["changes_for"]


def changes_for(
    context: AutostartContext, conn: sqlite3.Connection, data_dir: Path
) -> XdgChanges | RunKeyChanges | None:
    """The registry is opened only on Windows."""
    if context.platform == "linux":
        user, system = autostart_dirs(context.env, context.home)
        return XdgChanges(conn, AutostartStore(data_dir), user, system)
    if context.platform == "windows":
        return RunKeyChanges(conn, context.registry())
    return None
