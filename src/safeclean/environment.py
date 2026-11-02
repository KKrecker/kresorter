"""What the commands take from the system they run on, one object for the CLI and the UI.

Each part is built only when a command needs it: ``autostart list`` makes no scan context and
``llm status`` neither. Tests give an ``Environment`` of their own, made for tmp_path.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

from safeclean.autostart.listing import AutostartContext, default_autostart_context
from safeclean.core.heuristics import JunkClassifier, Platform, default_rules
from safeclean.core.open_files import checker_for_platform
from safeclean.core.policy import PathPolicy
from safeclean.core.scanner import ScanContext
from safeclean.llm.transport import LIMITS, Limits

__all__ = ["Environment", "default_context", "detect_platform"]

_PLATFORMS: dict[str, Platform] = {"win32": "windows", "linux": "linux", "darwin": "darwin"}


def detect_platform(sys_platform: str = sys.platform) -> Platform:
    try:
        return _PLATFORMS[sys_platform]
    except KeyError:
        raise RuntimeError(f"unsupported platform: {sys_platform}") from None


def default_context(
    platform: Platform | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> ScanContext:
    """Context for the current system (arguments exist for tests)."""
    current = platform or detect_platform()
    if current == "windows":
        policy = PathPolicy.for_windows(os.environ if env is None else env)
    else:
        posix: Literal["linux", "darwin"] = "darwin" if current == "darwin" else "linux"
        policy = PathPolicy.for_posix(
            home=PurePosixPath(home or Path.home()),
            platform=posix,
            env=os.environ if env is None else env,
        )
    open_files = checker_for_platform(current)
    return ScanContext(
        policy=policy,
        open_files=open_files,
        classifier=JunkClassifier(default_rules(), platform=current),
        open_files_checked=open_files.reliable,
        platform=current,
    )


def _scan_context() -> ScanContext:
    return default_context()


def _autostart_context() -> AutostartContext:
    return default_autostart_context(detect_platform())


def _process_env() -> Mapping[str, str]:
    return os.environ


@dataclass(frozen=True)
class Environment:
    """``scan_context`` and ``autostart_context`` build the contexts of the running system;
    ``llm_env`` is read only by ``llm status`` and ``--explain``, ``llm_limits`` bounds their
    requests (pre-step-5 audit, B8)."""

    scan_context: Callable[[], ScanContext] = _scan_context
    autostart_context: Callable[[], AutostartContext] = _autostart_context
    llm_env: Mapping[str, str] = field(default_factory=_process_env)
    llm_limits: Limits = LIMITS
