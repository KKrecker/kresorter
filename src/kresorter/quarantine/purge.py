"""The only code in kresorter that deletes a file (decisions 0001, 0004 item 8, 0008).

It deletes one regular file in a vault slot ``<vault>/<operation id>/<item id>`` and nothing
else. Kept small on purpose: the whole safety argument fits on one screen.
"""

from __future__ import annotations

import stat
from pathlib import Path


class UnsafeDeleteError(Exception):
    """The path is not a regular file in a vault slot; nothing was deleted.

    Deliberately not an ``OSError``: callers retry OS errors, this one is a bug.
    """


def delete_from_vault(vault_root: Path, path: Path) -> None:
    if not (vault_root.is_absolute() and path.is_absolute()):
        raise UnsafeDeleteError(f"refusing to delete {path}: not an absolute path")
    if not path.is_relative_to(vault_root):
        raise UnsafeDeleteError(f"refusing to delete {path}: outside the vault {vault_root}")
    parts = path.relative_to(vault_root).parts
    if len(parts) != 2 or not all(part.isascii() and part.isdecimal() for part in parts):
        raise UnsafeDeleteError(f"refusing to delete {path}: not a vault slot")
    # Links inside the vault are suspicious; a vault reached through a link is not.
    if path.parent.resolve() != vault_root.resolve() / parts[0]:
        raise UnsafeDeleteError(f"refusing to delete {path}: the operation directory is a link")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise UnsafeDeleteError(f"refusing to delete {path}: not a regular file")
    path.unlink()
