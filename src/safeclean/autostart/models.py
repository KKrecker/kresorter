"""Autostart items as read from one source, with their effective state (decision 0011)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from hashlib import blake2b

DIGEST_SIZE = 16  # bytes; 32 hex characters
_DIGEST = re.compile(r"[0-9a-f]{32}")


class Source(StrEnum):
    XDG_AUTOSTART = "xdg_autostart"
    SYSTEMD_USER = "systemd_user"
    RUN_KEY = "run_key"
    RUN_ONCE_KEY = "run_once_key"
    STARTUP_FOLDER = "startup_folder"
    SERVICE = "service"
    SCHEDULED_TASK = "scheduled_task"
    LAUNCH_AGENT = "launch_agent"


class Scope(StrEnum):
    """Where the entry lives: the user's own files and HKCU, or the system's."""

    USER = "user"
    SYSTEM = "system"


def entry_digest(raw: bytes) -> str:
    """Fingerprint of a raw entry as read, compared again right before any action."""
    return blake2b(raw, digest_size=DIGEST_SIZE).hexdigest()


@dataclass(frozen=True)
class AutostartItem:
    source: Source
    scope: Scope
    name: str
    command: str
    location: str  # the file or registry value in effect
    enabled: bool  # effective state
    digest: str  # entry_digest() of the raw entry at `location`
    shadows: str | None = None  # XDG only: the system file a user entry replaces
    notes: tuple[str, ...] = ()  # conditions reported as they are, never evaluated

    def __post_init__(self) -> None:
        for field in ("name", "command", "location"):
            if not getattr(self, field):
                raise ValueError(f"{field} must not be empty")
        if not _DIGEST.fullmatch(self.digest):
            raise ValueError(f"digest must be {DIGEST_SIZE * 2} lowercase hex characters")
        user_xdg = self.source is Source.XDG_AUTOSTART and self.scope is Scope.USER
        if self.shadows is not None and not user_xdg:
            raise ValueError("only a user XDG entry shadows a system file")

    @property
    def disableable(self) -> bool:
        """Step 4 disables XDG entries and HKCU Run values only (decision 0011, item 8)."""
        if self.source is Source.XDG_AUTOSTART:
            return True
        return self.source is Source.RUN_KEY and self.scope is Scope.USER


@dataclass(frozen=True)
class AutostartSkipped:
    """An entry that could not be read; listed with the reason, never fatal."""

    source: Source
    location: str
    detail: str


@dataclass(frozen=True)
class AutostartListing:
    items: tuple[AutostartItem, ...]
    skipped: tuple[AutostartSkipped, ...]
