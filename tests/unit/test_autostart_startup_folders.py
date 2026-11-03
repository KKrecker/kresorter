"""Reading Windows startup folders (step 4, commit 7; decision 0011).

The user folder is always read; the common one (all users) only with ``include_machine``, as
its state lives in ``HKLM``. One item per file; ``desktop.ini`` is the folder's own settings,
not an entry. The state is the file's flag in ``Explorer\\StartupApproved\\StartupFolder`` of
the same hive, read like the Run flags: no flag is enabled, an unknown one is not shown (item
12). The command is the file itself, as Explorer opens it; shortcut targets are not resolved.
Folders are real temporary trees; the registry is a fake.
"""

from pathlib import Path

import pytest

from fakes import FakeRegistry, RegistryKeys
from kresorter.autostart.models import (
    AutostartItem,
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
)
from kresorter.autostart.registry import Hive, Registry, RegValue, ValueKind
from kresorter.autostart.startup_folders import (
    MAX_ENTRY_BYTES,
    STARTUP_APPROVED,
    read_startup_folders,
    startup_dirs,
)

ENABLED = bytes([0x02]) + bytes(11)
DISABLED = bytes([0x03]) + bytes(3) + bytes(range(8))  # flag, padding, FILETIME of the change
LINK = b"L\x00\x00\x00" + bytes(72)  # starts like a Shell Link file; never parsed


def entry(directory: Path, name: str, raw: bytes = LINK) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(raw)
    return path


def flag(name: str, data: bytes) -> RegValue:
    return RegValue(name, ValueKind.REG_BINARY, data)


@pytest.fixture
def user(tmp_path: Path) -> Path:
    return tmp_path / "AppData" / "Roaming" / "Startup"


@pytest.fixture
def common(tmp_path: Path) -> Path:
    return tmp_path / "ProgramData" / "StartUp"


def read(
    user: Path | None,
    common: Path | None = None,
    keys: RegistryKeys | None = None,
    *,
    include_machine: bool = False,
) -> AutostartListing:
    registry: Registry = FakeRegistry(keys or {})
    return read_startup_folders(registry, user, common, include_machine=include_machine)


def only(listing: AutostartListing) -> AutostartItem:
    (item,) = listing.items
    assert listing.skipped == ()
    return item


# --- items ---------------------------------------------------------------------------------


def test_a_file_in_the_user_folder_without_a_flag_is_enabled(user: Path) -> None:
    path = entry(user, "Sync.lnk")

    found = only(read(user))

    assert found.source is Source.STARTUP_FOLDER
    assert found.scope is Scope.USER
    assert found.name == "Sync.lnk"
    assert found.command == str(path)
    assert found.location == str(path)
    assert found.enabled is True
    assert found.notes == ()
    assert found.disableable is False


@pytest.mark.parametrize(
    ("data", "enabled"),
    [
        (ENABLED, True),
        (bytes([0x06]) + bytes(11), True),
        (DISABLED, False),
        (bytes([0x07]) + bytes(11), False),
    ],
)
def test_startup_approved_decides_the_state(user: Path, data: bytes, enabled: bool) -> None:
    entry(user, "Sync.lnk")
    keys = {(Hive.HKCU, STARTUP_APPROVED): [flag("Sync.lnk", data)]}

    assert only(read(user, keys=keys)).enabled is enabled


def test_a_disabled_file_names_the_key_that_disables_it(user: Path) -> None:
    entry(user, "Sync.lnk")
    keys = {(Hive.HKCU, STARTUP_APPROVED): [flag("SYNC.LNK", DISABLED)]}

    found = only(read(user, keys=keys))

    assert found.enabled is False
    assert found.notes == (rf"disabled in HKCU\{STARTUP_APPROVED}",)


def test_a_flag_without_a_file_is_not_an_item(user: Path) -> None:
    user.mkdir(parents=True)
    keys = {(Hive.HKCU, STARTUP_APPROVED): [flag("Gone.lnk", ENABLED)]}

    assert read(user, keys=keys) == AutostartListing((), ())


def test_any_kind_of_file_is_listed_as_it_is(user: Path) -> None:
    entry(user, "start.cmd", b"@echo off\r\nstart sync.exe\r\n")
    entry(user, "notes.txt", b"")

    assert [i.name for i in read(user).items] == ["notes.txt", "start.cmd"]


def test_desktop_ini_is_the_folder_settings_not_an_entry(user: Path) -> None:
    entry(user, "Desktop.ini", b"[.ShellClassInfo]\r\n")

    assert read(user) == AutostartListing((), ())


def test_items_are_ordered_user_first_then_by_name_ignoring_case(user: Path, common: Path) -> None:
    for name in ("b.lnk", "A.lnk"):
        entry(user, name)
        entry(common, name)

    listing = read(user, common, include_machine=True)

    assert [(i.scope, i.name) for i in listing.items] == [
        (Scope.USER, "A.lnk"),
        (Scope.USER, "b.lnk"),
        (Scope.SYSTEM, "A.lnk"),
        (Scope.SYSTEM, "b.lnk"),
    ]


# --- the common folder ---------------------------------------------------------------------


def test_the_common_folder_is_not_even_read_without_consent(user: Path, common: Path) -> None:
    entry(common, "Agent.lnk")
    registry = FakeRegistry({})

    listing = read_startup_folders(registry, user, common, include_machine=False)

    assert listing == AutostartListing((), ())
    assert Hive.HKLM not in {hive for hive, _ in registry.reads}


def test_common_files_are_system_scope_and_use_machine_flags(user: Path, common: Path) -> None:
    entry(common, "Agent.lnk")
    keys = {
        (Hive.HKCU, STARTUP_APPROVED): [flag("Agent.lnk", ENABLED)],
        (Hive.HKLM, STARTUP_APPROVED): [flag("Agent.lnk", DISABLED)],
    }

    found = only(read(user, common, keys, include_machine=True))

    assert found.scope is Scope.SYSTEM
    assert found.enabled is False
    assert found.notes == (rf"disabled in HKLM\{STARTUP_APPROVED}",)
    assert found.disableable is False


def test_a_folder_that_is_not_known_is_not_read(common: Path) -> None:
    entry(common, "Agent.lnk")

    assert read(None, None, include_machine=True) == AutostartListing((), ())
    assert len(read(None, common, include_machine=True).items) == 1


# --- what is skipped -----------------------------------------------------------------------


def test_a_missing_folder_gives_an_empty_listing(user: Path, common: Path) -> None:
    assert read(user, common, include_machine=True) == AutostartListing((), ())


def test_a_folder_that_cannot_be_listed_is_skipped(tmp_path: Path) -> None:
    not_a_folder = entry(tmp_path, "Startup")

    listing = read(not_a_folder)

    (skipped,) = listing.skipped
    assert listing.items == ()
    assert skipped.source is Source.STARTUP_FOLDER
    assert skipped.location == str(not_a_folder)
    assert skipped.detail.startswith("cannot read: ")


def test_a_directory_inside_the_folder_is_skipped(user: Path) -> None:
    inner = user / "Tools"
    inner.mkdir(parents=True)

    assert read(user) == AutostartListing(
        (), (AutostartSkipped(Source.STARTUP_FOLDER, str(inner), "not a regular file"),)
    )


def test_a_file_too_large_to_fingerprint_is_skipped(user: Path) -> None:
    path = entry(user, "big.exe", bytes(MAX_ENTRY_BYTES + 1))

    (skipped,) = read(user).skipped

    assert skipped == AutostartSkipped(
        Source.STARTUP_FOLDER, str(path), f"larger than {MAX_ENTRY_BYTES} bytes"
    )


@pytest.mark.parametrize(
    ("approved", "detail"),
    [
        (flag("Sync.lnk", bytes([0x01]) + bytes(11)), "unknown StartupApproved state 0x01"),
        (flag("Sync.lnk", b""), "unknown StartupApproved state (empty)"),
        (RegValue("Sync.lnk", ValueKind.REG_DWORD, 2), "StartupApproved value is not binary"),
    ],
)
def test_an_unknown_state_is_skipped_not_shown(user: Path, approved: RegValue, detail: str) -> None:
    path = entry(user, "Sync.lnk")

    listing = read(user, keys={(Hive.HKCU, STARTUP_APPROVED): [approved]})

    assert listing == AutostartListing(
        (), (AutostartSkipped(Source.STARTUP_FOLDER, str(path), detail),)
    )


def test_an_unreadable_flag_key_makes_every_state_unknown(user: Path, common: Path) -> None:
    entry(user, "Sync.lnk")
    entry(common, "Agent.lnk")
    registry = FakeRegistry({}, denied=[(Hive.HKCU, STARTUP_APPROVED)])

    listing = read_startup_folders(registry, user, common, include_machine=True)

    assert [i.name for i in listing.items] == ["Agent.lnk"]
    assert listing.skipped == (
        AutostartSkipped(
            Source.STARTUP_FOLDER, rf"HKCU\{STARTUP_APPROVED}", "cannot read: access denied"
        ),
    )


def test_flags_are_not_read_for_an_empty_folder(user: Path) -> None:
    user.mkdir(parents=True)
    registry = FakeRegistry({}, denied=[(Hive.HKCU, STARTUP_APPROVED)])

    assert read_startup_folders(registry, user, None, include_machine=False).skipped == ()
    assert registry.reads == []


# --- the digest ----------------------------------------------------------------------------


def test_the_digest_changes_with_the_file_and_its_flag(user: Path) -> None:
    path = entry(user, "Sync.lnk", b"one")
    disabled = {(Hive.HKCU, STARTUP_APPROVED): [flag("Sync.lnk", DISABLED)]}
    enabled = {(Hive.HKCU, STARTUP_APPROVED): [flag("Sync.lnk", ENABLED)]}

    base = only(read(user)).digest
    assert only(read(user)).digest == base
    with_flag = only(read(user, keys=enabled)).digest
    assert with_flag != base
    assert only(read(user, keys=disabled)).digest != with_flag
    path.write_bytes(b"two")
    assert only(read(user)).digest != base


def test_the_digest_keeps_the_file_and_the_flag_apart(user: Path, common: Path) -> None:
    entry(user, "x", b"a\x02")
    entry(common, "x", b"a")
    keys = {(Hive.HKLM, STARTUP_APPROVED): [flag("x", b"\x02")]}

    with_flag = read(None, common, keys, include_machine=True)

    assert only(read(user)).digest != only(with_flag).digest


# --- where the folders are -----------------------------------------------------------------


def test_the_folders_come_from_appdata_and_programdata(tmp_path: Path) -> None:
    env = {"APPDATA": str(tmp_path / "Roaming"), "ProgramData": str(tmp_path / "ProgramData")}
    programs = Path("Microsoft", "Windows", "Start Menu", "Programs")

    assert startup_dirs(env) == (
        tmp_path / "Roaming" / programs / "Startup",
        tmp_path / "ProgramData" / programs / "StartUp",
    )


@pytest.mark.parametrize("value", ["", "relative"])
def test_an_unset_or_relative_variable_means_no_folder(tmp_path: Path, value: str) -> None:
    env = {"APPDATA": value, "ProgramData": str(tmp_path)}

    user, common = startup_dirs(env)

    assert user is None
    assert common is not None
    assert startup_dirs({}) == (None, None)
