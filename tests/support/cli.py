"""Running the CLI in tests, with the contexts it would build for itself made for tmp_path."""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from fakes import FakeOpenFiles, FakeRegistry, make_policy
from kresorter import cli
from kresorter.autostart.listing import AutostartContext
from kresorter.autostart.registry import UserRegistry
from kresorter.core.heuristics import Platform
from kresorter.core.open_files import OpenFileChecker
from kresorter.core.scanner import ScanContext
from kresorter.environment import Environment
from kresorter.organize.synced import NoSyncedFolders, SyncedFolders
from support.host import host_classifier, host_rules


def scan_context(
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    open_files: OpenFileChecker | None = None,
    *,
    platform: Platform = "linux",
    synced: SyncedFolders | None = None,
) -> ScanContext:
    """``zone`` the one default root, ``data_dir`` the data directory, the running system's
    rules but the one that marks tmp_path as junk (``support.host.host_rules``), so that the
    data directory does not look like junk and get refused. ``platform`` is the system the
    context says it was made for; its rules stay the running system's, which read the temporary
    paths of the tests. No folder is synced unless ``synced`` names some."""
    rules = host_rules()
    checker = open_files or FakeOpenFiles()
    policy = make_policy(tmp_path, tmp_path / "system", default_roots=[zone], app_data_dir=data_dir)
    return ScanContext(
        policy=policy,
        open_files=checker,
        classifier=host_classifier(rules),
        open_files_checked=checker.reliable,
        platform=platform,
        synced=NoSyncedFolders() if synced is None else synced,
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
    """``kresorter <args>``: exit code, stdout, stderr."""
    out, err = io.StringIO(), io.StringIO()
    environment = Environment(scan_context=lambda: scan)
    if auto is not None:
        environment = replace(environment, autostart_context=_given(auto))
    code = cli.main(args, out=out, err=err, environment=environment)
    return code, out.getvalue(), err.getvalue()


def _given(auto: AutostartContext) -> Callable[[], AutostartContext]:
    return lambda: auto
