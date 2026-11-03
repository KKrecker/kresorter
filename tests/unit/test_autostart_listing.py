"""One autostart listing for the current system (step 4, commit 10a; decision 0011).

Each platform has its readers: Linux reads XDG autostart and systemd user units, Windows the
Run keys, startup folders, services and scheduled tasks, macOS launchd. Their listings are
joined in that order. The registry is created only on Windows, once, and only when used;
nothing else of the live system is read: the context names every directory.
"""

import plistlib
from dataclasses import replace
from pathlib import Path

from fakes import FakeRegistry
from kresorter.autostart.listing import (
    AutostartContext,
    RegistryFactory,
    default_autostart_context,
    list_autostart,
)
from kresorter.autostart.models import AutostartSkipped, Scope, Source
from kresorter.autostart.registry import Hive, RegValue, UserRegistry, ValueKind
from kresorter.autostart.run_keys import RUN
from kresorter.autostart.services import SERVICES
from kresorter.autostart.winregistry import WinRegistry
from kresorter.core.heuristics import Platform
from support.files import write

DESKTOP = b"[Desktop Entry]\nType=Application\nName=App\nExec=/usr/bin/app\n"
UNIT = b"[Service]\nExecStart=/usr/bin/sync\n"
TASK = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
    b"<Triggers><LogonTrigger/></Triggers><Actions><Exec><Command>t.exe</Command></Exec>"
    b"</Actions></Task>"
)


def no_registry() -> UserRegistry:
    raise AssertionError("the registry is only for Windows")


class CountingFactory:
    def __init__(self, registry: FakeRegistry) -> None:
        self.registry = registry
        self.calls = 0

    def __call__(self) -> UserRegistry:
        self.calls += 1
        return self.registry


def context(
    platform: Platform, tmp_path: Path, factory: RegistryFactory = no_registry
) -> AutostartContext:
    env = {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CONFIG_DIRS": str(tmp_path / "etc" / "xdg"),
        "APPDATA": str(tmp_path / "Roaming"),
        "ProgramData": str(tmp_path / "ProgramData"),
        "SystemRoot": str(tmp_path / "Windows"),
    }
    return AutostartContext(platform, env, home=tmp_path / "home", root=tmp_path, registry=factory)


# --- Linux ---------------------------------------------------------------------------------------


def test_linux_lists_xdg_then_systemd_user_units(tmp_path: Path) -> None:
    write(tmp_path / "etc" / "xdg" / "autostart" / "app.desktop", DESKTOP)
    units = tmp_path / "config" / "systemd" / "user"
    unit = write(units / "sync.service", UNIT)
    (units / "default.target.wants").mkdir()
    (units / "default.target.wants" / "sync.service").symlink_to(unit)

    listing = list_autostart(context("linux", tmp_path), include_machine=False)

    assert [(i.source, i.name) for i in listing.items] == [
        (Source.XDG_AUTOSTART, "app"),
        (Source.SYSTEMD_USER, "sync.service"),
    ]


def test_linux_joins_the_skips_of_every_reader_in_order(tmp_path: Path) -> None:
    bad = write(tmp_path / "config" / "autostart" / "bad.desktop", b"not an entry")
    units = tmp_path / "config" / "systemd" / "user" / "default.target.wants"
    units.mkdir(parents=True)
    (units / "gone.service").symlink_to(tmp_path / "missing.service")

    listing = list_autostart(context("linux", tmp_path), include_machine=True)

    assert [(s.source, s.location) for s in listing.skipped] == [
        (Source.XDG_AUTOSTART, str(bad)),
        (Source.SYSTEMD_USER, str(units / "gone.service")),
    ]


# --- Windows -------------------------------------------------------------------------------------


def windows(tmp_path: Path) -> CountingFactory:
    programs = Path("Microsoft", "Windows", "Start Menu", "Programs")
    write(tmp_path / "Roaming" / programs / "Startup" / "a.lnk", b"L")
    write(tmp_path / "Windows" / "System32" / "Tasks" / "AtLogon", TASK)
    service = [
        RegValue("Type", ValueKind.REG_DWORD, 0x10),
        RegValue("Start", ValueKind.REG_DWORD, 2),
        RegValue("ImagePath", ValueKind.REG_SZ, "svc.exe"),
    ]
    run = [RegValue("Sync", ValueKind.REG_SZ, "sync.exe")]
    keys = {(Hive.HKCU, RUN): run, (Hive.HKLM, RUN): run, (Hive.HKLM, rf"{SERVICES}\Svc"): service}
    return CountingFactory(FakeRegistry(keys))


def test_windows_reads_the_user_scope_only_without_consent(tmp_path: Path) -> None:
    factory = windows(tmp_path)

    listing = list_autostart(context("windows", tmp_path, factory), include_machine=False)

    assert [(i.source, i.scope) for i in listing.items] == [
        (Source.RUN_KEY, Scope.USER),
        (Source.STARTUP_FOLDER, Scope.USER),
    ]
    assert Hive.HKLM not in {hive for hive, _ in factory.registry.reads}


def test_windows_with_consent_adds_the_machine_and_uses_one_registry(tmp_path: Path) -> None:
    factory = windows(tmp_path)

    listing = list_autostart(context("windows", tmp_path, factory), include_machine=True)

    assert [(i.source, i.scope) for i in listing.items] == [
        (Source.RUN_KEY, Scope.USER),
        (Source.RUN_KEY, Scope.SYSTEM),
        (Source.STARTUP_FOLDER, Scope.USER),
        (Source.SERVICE, Scope.SYSTEM),
        (Source.SCHEDULED_TASK, Scope.SYSTEM),
    ]
    assert factory.calls == 1


def test_windows_without_known_folders_still_reads_the_registry(tmp_path: Path) -> None:
    factory = windows(tmp_path)
    ctx = replace(context("windows", tmp_path, factory), env={})

    listing = list_autostart(ctx, include_machine=True)

    assert [i.source for i in listing.items] == [Source.RUN_KEY, Source.RUN_KEY, Source.SERVICE]


# --- macOS ---------------------------------------------------------------------------------------


def test_macos_lists_launchd_under_the_home_and_the_root(tmp_path: Path) -> None:
    agent = {"Label": "com.example.a", "Program": "/bin/a"}
    write(tmp_path / "home" / "Library" / "LaunchAgents" / "a.plist", plistlib.dumps(agent))
    write(tmp_path / "Library" / "LaunchDaemons" / "d.plist", plistlib.dumps(agent))

    listing = list_autostart(context("darwin", tmp_path), include_machine=False)

    assert [(i.source, i.scope) for i in listing.items] == [
        (Source.LAUNCH_AGENT, Scope.USER),
        (Source.LAUNCH_AGENT, Scope.SYSTEM),
    ]
    assert listing.skipped == ()


# --- the context of the current system -----------------------------------------------------------


def test_the_default_context_describes_the_running_system(tmp_path: Path) -> None:
    ctx = default_autostart_context(platform="linux", env={"A": "1"}, home=tmp_path)

    assert ctx.platform == "linux"
    assert ctx.env == {"A": "1"}
    assert ctx.home == tmp_path
    assert ctx.root == Path("/")
    assert ctx.registry is WinRegistry


def test_skips_keep_their_reader(tmp_path: Path) -> None:
    bad = write(tmp_path / "Library" / "LaunchAgents" / "bad.plist", b"nope")

    listing = list_autostart(context("darwin", tmp_path), include_machine=False)

    assert listing.skipped == (
        AutostartSkipped(Source.LAUNCH_AGENT, str(bad), "not a valid property list"),
    )
