"""The folders a sync client keeps, which organize refuses as a whole (decision 0017, items 8-10).

On Windows they are those Windows names: the values of OneDrive's variables, and every string
value of every root's ``UserSyncRoots`` under ``SyncRootManager``, the key where each client
of the Cloud Files API registers its root, one value per user. Both are read each time they
are asked, so a root registered since counts. A key that exists but cannot be read leaves them
unknown, and organize then refuses every folder. Linux and macOS name none.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import PurePath, PureWindowsPath
from typing import Protocol

from kresorter.autostart.registry import Hive, Registry, RegistryError, RegValue, ValueKind
from kresorter.autostart.winregistry import WinRegistry

__all__ = [
    "NoSyncedFolders",
    "SyncedFolders",
    "SyncedFoldersUnknown",
    "WindowsSyncedFolders",
]

MANAGER = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager"
VARIABLES = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
_EXPANDED = re.compile(r"%([^%]+)%")


class SyncedFoldersUnknown(Exception):
    """The synced folders cannot be told; the message says why."""


class SyncedFolders(Protocol):
    def folders(self) -> tuple[PurePath, ...]:
        """The synced folders, as the system names them now. Raises SyncedFoldersUnknown."""


class NoSyncedFolders:
    """Linux and macOS, and a context made for another system: no folder is synced."""

    def folders(self) -> tuple[PurePath, ...]:
        return ()


class WindowsSyncedFolders:
    """``env`` is the environment, the process's when ``None``, read at each call as the
    registry is; names are looked up in any case, as Windows does."""

    def __init__(
        self, env: Mapping[str, str] | None = None, registry: Registry | None = None
    ) -> None:
        self._env = env
        self.registry: Registry = WinRegistry() if registry is None else registry

    def folders(self) -> tuple[PurePath, ...]:
        given = os.environ if self._env is None else self._env
        env = {name.casefold(): value for name, value in given.items()}
        found = [env.get(name.casefold(), "") for name in VARIABLES]
        try:
            for root in sorted(self.registry.subkeys(Hive.HKLM, MANAGER) or ()):
                values = self.registry.values(Hive.HKLM, rf"{MANAGER}\{root}\UserSyncRoots")
                found += [_path(value, env) for value in values or ()]
        except RegistryError as error:
            raise SyncedFoldersUnknown(str(error)) from None
        return tuple(PureWindowsPath(path) for path in found if path)


def _path(value: RegValue, env: Mapping[str, str]) -> str:
    """The path a value holds, ``""`` for one that is not a string."""
    if not isinstance(value.data, str):
        return ""
    if value.kind == ValueKind.REG_SZ:
        return value.data
    if value.kind == ValueKind.REG_EXPAND_SZ:
        return _EXPANDED.sub(lambda name: env.get(name[1].casefold(), name[0]), value.data)
    return ""
