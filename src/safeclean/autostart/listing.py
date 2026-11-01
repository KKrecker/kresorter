"""One autostart listing for the current system: each platform's readers, joined (0011).

Linux reads XDG autostart, then systemd user units; Windows the Run keys, startup folders,
services, then scheduled tasks; macOS launchd. The context names everything read from the
live system; the registry is created on Windows only, once per listing. Read-only.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from safeclean.autostart.launchd import launchd_dirs, read_launchd
from safeclean.autostart.models import AutostartListing
from safeclean.autostart.registry import UserRegistry
from safeclean.autostart.run_keys import read_run_keys
from safeclean.autostart.services import read_services
from safeclean.autostart.startup_folders import read_startup_folders, startup_dirs
from safeclean.autostart.systemd import read_systemd_user, systemd_user_dir
from safeclean.autostart.tasks import read_tasks, tasks_dir
from safeclean.autostart.winregistry import WinRegistry
from safeclean.autostart.xdg import autostart_dirs, read_xdg
from safeclean.core.heuristics import Platform

RegistryFactory = Callable[[], UserRegistry]  # read by listings, written by changes


@dataclass(frozen=True)
class AutostartContext:
    """What a listing reads: the platform, its environment and directories, the registry."""

    platform: Platform
    env: Mapping[str, str]
    home: Path
    root: Path  # "/" on a live system; launchd's /Library is under it
    registry: RegistryFactory  # called on Windows only


def default_autostart_context(
    platform: Platform, env: Mapping[str, str] | None = None, home: Path | None = None
) -> AutostartContext:
    """The running system; the caller detects ``platform``, so this module knows no CLI."""
    return AutostartContext(
        platform=platform,
        env=os.environ if env is None else env,
        home=home or Path.home(),
        root=Path("/"),
        registry=WinRegistry,
    )


def list_autostart(context: AutostartContext, *, include_machine: bool) -> AutostartListing:
    return _join(_READERS[context.platform](context, include_machine))


def _linux(context: AutostartContext, include_machine: bool) -> list[AutostartListing]:
    """``include_machine`` changes nothing here, nor on macOS: no machine scope needs consent."""
    user, system = autostart_dirs(context.env, context.home)
    return [read_xdg(user, system), read_systemd_user(systemd_user_dir(context.env, context.home))]


def _windows(context: AutostartContext, include_machine: bool) -> list[AutostartListing]:
    registry = context.registry()
    user, common = startup_dirs(context.env)
    return [
        read_run_keys(registry, include_machine=include_machine),
        read_startup_folders(registry, user, common, include_machine=include_machine),
        read_services(registry, include_machine=include_machine),
        read_tasks(tasks_dir(context.env), include_machine=include_machine),
    ]


def _darwin(context: AutostartContext, include_machine: bool) -> list[AutostartListing]:
    return [read_launchd(*launchd_dirs(context.home, context.root))]


_READERS: dict[Platform, Callable[[AutostartContext, bool], list[AutostartListing]]] = {
    "linux": _linux,
    "windows": _windows,
    "darwin": _darwin,
}


def _join(listings: list[AutostartListing]) -> AutostartListing:
    items = tuple(item for listing in listings for item in listing.items)
    return AutostartListing(items, tuple(skip for listing in listings for skip in listing.skipped))
