"""Running the CLI in tests, with the contexts it would build for itself made for tmp_path."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

from fakes import FakeOpenFiles, FakeRegistry, make_policy
from safeclean import cli
from safeclean.autostart.listing import AutostartContext
from safeclean.autostart.registry import UserRegistry
from safeclean.core.heuristics import JunkClassifier, Platform, default_rules
from safeclean.core.open_files import OpenFileChecker
from safeclean.core.scanner import ScanContext


def scan_context(
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    open_files: OpenFileChecker | None = None,
    *,
    platform: Platform = "linux",
) -> ScanContext:
    """``zone`` the one default root, ``data_dir`` the data directory, every default rule but
    ``posix-temp``: tmp_path lives under /tmp, which it marks as junk, so the data directory
    itself would look like junk and be refused. ``platform`` is the system the context says it
    was made for; its rules stay Linux's, which read the temporary paths of the tests."""
    rules = [r for r in default_rules() if r.id != "posix-temp"]
    checker = open_files or FakeOpenFiles()
    policy = make_policy(tmp_path, tmp_path / "system", default_roots=[zone], app_data_dir=data_dir)
    return ScanContext(
        policy=policy,
        open_files=checker,
        classifier=JunkClassifier(rules, platform="linux"),
        open_files_checked=checker.reliable,
        platform=platform,
    )


def autostart_context(
    platform: Platform, tmp_path: Path, registry: UserRegistry | None = None
) -> AutostartContext:
    """Autostart on ``platform``, its XDG directories and home in tmp_path."""
    env = {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CONFIG_DIRS": str(tmp_path / "etc" / "xdg"),
    }
    return AutostartContext(
        platform, env, home=tmp_path, root=tmp_path, registry=lambda: registry or FakeRegistry({})
    )


def run(
    args: list[str], scan: ScanContext, auto: AutostartContext | None = None
) -> tuple[int, str, str]:
    """``safeclean <args>``: exit code, stdout, stderr."""
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        args,
        out=out,
        err=err,
        context_factory=lambda: scan,
        autostart_context=None if auto is None else _given(auto),
    )
    return code, out.getvalue(), err.getvalue()


def _given(auto: AutostartContext) -> Callable[[], AutostartContext]:
    return lambda: auto
