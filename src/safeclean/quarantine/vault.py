"""Vault: private storage for quarantined files under the app data directory (decision 0004).

Layout: ``<data_dir>/quarantine/<operation_id>/<item_id>``. Directories are 0700. The vault is
never inside a default scan zone; the service checks that before using it.
"""

from __future__ import annotations

from pathlib import Path

PRIVATE = 0o700


class Vault:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.root = data_dir / "quarantine"

    def ensure(self) -> None:
        """Create the vault if needed and make it private, also when it already existed."""
        self.root.mkdir(mode=PRIVATE, parents=True, exist_ok=True)
        self.data_dir.chmod(PRIVATE)
        self.root.chmod(PRIVATE)

    def device(self) -> int:
        """``st_dev`` of the vault: only same-device renames are allowed."""
        return self.root.stat().st_dev

    def slot(self, operation_id: int, item_id: int) -> Path:
        return self.root / str(operation_id) / str(item_id)

    def prepare(self, operation_id: int) -> Path:
        directory = self.root / str(operation_id)
        directory.mkdir(mode=PRIVATE, exist_ok=True)
        directory.chmod(PRIVATE)
        return directory
