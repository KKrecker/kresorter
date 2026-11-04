"""The synced folders Windows names, asked when organize plans a folder (decision 0017, items 9
and 10).

OneDrive sets three variables; every client of the Cloud Files API registers its root under
``SyncRootManager``, a value of ``UserSyncRoots`` per user. Both are read on fakes here: the
environment a mapping, the registry ``FakeRegistry``; the real registry is read on Windows.
"""

from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from fakes import FakeRegistry, RegistryKeys
from kresorter import environment
from kresorter.autostart.registry import Hive, RegValue, ValueKind
from kresorter.autostart.winregistry import WinRegistry
from kresorter.core.heuristics import Platform
from kresorter.organize.synced import (
    NoSyncedFolders,
    SyncedFoldersUnknown,
    WindowsSyncedFolders,
)

MANAGER = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager"
ANN = "S-1-5-21-1000"
BOB = "S-1-5-21-1001"
VARIABLES = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")


def roots_of(root: str) -> tuple[Hive, str]:
    return (Hive.HKLM, rf"{MANAGER}\{root}\UserSyncRoots")


def text(name: str, data: str, kind: ValueKind = ValueKind.REG_SZ) -> RegValue:
    return RegValue(name, kind, data)


def folders(env: dict[str, str], keys: RegistryKeys | None = None) -> list[str]:
    synced = WindowsSyncedFolders(env, FakeRegistry(keys or {}))
    return [str(folder) for folder in synced.folders()]


# --- the variables ------------------------------------------------------------------------------


def test_the_onedrive_variables_name_synced_folders() -> None:
    # [0017.9] the three of them, in this order, as Windows paths
    env = {
        "OneDriveCommercial": r"C:\Users\Ann\OneDrive - Contoso",
        "OneDrive": r"C:\Users\Ann\OneDrive",
        "OneDriveConsumer": r"D:\Ann\OneDrive",
        "USERPROFILE": r"C:\Users\Ann",
    }
    synced = WindowsSyncedFolders(env, FakeRegistry({}))
    assert synced.folders() == (
        PureWindowsPath(r"C:\Users\Ann\OneDrive"),
        PureWindowsPath(r"D:\Ann\OneDrive"),
        PureWindowsPath(r"C:\Users\Ann\OneDrive - Contoso"),
    )


def test_the_variables_are_named_in_any_case() -> None:
    # [0017.9] as Windows names them: its environment is the same in every case
    assert folders({"ONEDRIVE": r"C:\Users\Ann\OneDrive"}) == [r"C:\Users\Ann\OneDrive"]


def test_an_empty_or_another_variable_names_nothing() -> None:
    # [0017.9]
    env = {"OneDrive": "", "OneDrive2": r"C:\Two", "OneDriveCommercialX": r"C:\X"}
    assert folders(env) == []


def test_without_an_environment_the_process_s_is_read_at_each_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0017.10] read each time, not when made
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)
    synced = WindowsSyncedFolders(registry=FakeRegistry({}))
    assert synced.folders() == ()
    monkeypatch.setenv("OneDrive", r"C:\Users\Ann\OneDrive")
    assert synced.folders() == (PureWindowsPath(r"C:\Users\Ann\OneDrive"),)


# --- the registry ------------------------------------------------------------------------------


def test_every_root_names_the_folders_of_every_user() -> None:
    # [0017.9] whichever user a value names; the roots in the order of their names
    keys = {
        roots_of(rf"OneDrive!{ANN}!Personal"): [text(ANN, r"C:\Users\Ann\OneDrive")],
        roots_of(rf"Dropbox!{ANN}!Personal"): [
            text(ANN, r"C:\Users\Ann\Dropbox"),
            text(BOB, r"C:\Users\Bob\Dropbox"),
        ],
    }
    assert folders({}, keys) == [
        r"C:\Users\Ann\Dropbox",
        r"C:\Users\Bob\Dropbox",
        r"C:\Users\Ann\OneDrive",
    ]


def test_the_variables_come_before_the_registry() -> None:
    # [0017.9]
    keys = {roots_of("Box"): [text(ANN, r"C:\Users\Ann\Box")]}
    env = {"OneDrive": r"C:\Users\Ann\OneDrive"}
    assert folders(env, keys) == [r"C:\Users\Ann\OneDrive", r"C:\Users\Ann\Box"]


def test_an_expandable_string_has_its_variables_expanded() -> None:
    # [0017.9] in any case, as Windows expands them; one it does not know is left as written
    keys = {
        roots_of("Box"): [
            text(ANN, r"%UserProfile%\Box", ValueKind.REG_EXPAND_SZ),
            text(BOB, r"%HOMEDRIVE%\%NOWHERE%\Box", ValueKind.REG_EXPAND_SZ),
        ]
    }
    env = {"USERPROFILE": r"C:\Users\Ann", "HomeDrive": "D:"}
    assert folders(env, keys) == [r"C:\Users\Ann\Box", r"D:\%NOWHERE%\Box"]


def test_a_plain_string_is_not_expanded() -> None:
    # [0017.9] REG_SZ is the path as written
    keys = {roots_of("Box"): [text(ANN, r"C:\%USERPROFILE%\Box")]}
    assert folders({"USERPROFILE": r"C:\Users\Ann"}, keys) == [r"C:\%USERPROFILE%\Box"]


def test_a_value_of_another_kind_or_an_empty_one_is_skipped() -> None:
    # [0017.9] not a path
    keys = {
        roots_of("Box"): [
            RegValue("binary", ValueKind.REG_BINARY, b"C:\\Box"),
            RegValue("number", ValueKind.REG_DWORD, 1),
            RegValue("list", ValueKind.REG_MULTI_SZ, [r"C:\Box"]),
            RegValue("none", ValueKind.REG_NONE, None),
            RegValue("unknown", 99, r"C:\Box"),
            text("empty", ""),
            text(ANN, r"C:\Users\Ann\Box"),
        ]
    }
    assert folders({}, keys) == [r"C:\Users\Ann\Box"]


def test_missing_keys_name_nothing() -> None:
    # [0017.9] no SyncRootManager, or a root without UserSyncRoots
    assert folders({}) == []
    assert folders({}, {(Hive.HKLM, rf"{MANAGER}\Box\Other"): []}) == []


def test_the_registry_is_read_at_each_call() -> None:
    # [0017.10] read each time organize plans a folder, so what a client registers since counts
    registry = FakeRegistry({roots_of("Box"): [text(ANN, r"C:\Users\Ann\Box")]})
    synced = WindowsSyncedFolders({}, registry)
    synced.folders()
    first = list(registry.reads)
    synced.folders()
    assert first == [(Hive.HKLM, MANAGER), roots_of("Box")]
    assert registry.reads == first * 2


@pytest.mark.parametrize("denied", [(Hive.HKLM, MANAGER), roots_of("Box")])
def test_a_key_that_cannot_be_read_leaves_the_synced_folders_unknown(
    denied: tuple[Hive, str],
) -> None:
    # [0017.10] failing closed: organize then refuses every folder
    registry = FakeRegistry({roots_of("Box"): [text(ANN, r"C:\Users\Ann\Box")]}, [denied])
    synced = WindowsSyncedFolders({"OneDrive": r"C:\Users\Ann\OneDrive"}, registry)
    with pytest.raises(SyncedFoldersUnknown, match=r"^access denied$"):
        synced.folders()


def test_the_registry_is_the_real_one_by_default() -> None:
    # [0017.10] made without reading it: winreg is imported when it is read
    assert isinstance(WindowsSyncedFolders().registry, WinRegistry)


# --- which context asks which --------------------------------------------------------------------


def test_linux_and_macos_name_no_synced_folder() -> None:
    # [0017.10]
    assert NoSyncedFolders().folders() == ()


def test_the_running_system_s_context_asks_its_system() -> None:
    # [0017.10] Windows its environment and its registry; Linux and macOS none
    context = environment.default_context()
    windows = environment.detect_platform() == "windows"
    assert type(context.synced) is (WindowsSyncedFolders if windows else NoSyncedFolders)


@pytest.mark.parametrize("platform", ["linux", "darwin", "windows"])
def test_a_context_for_another_system_names_no_synced_folder(platform: Platform) -> None:
    # [0017.10] the synced folders are the running system's, as its open-file check (0016.5)
    if platform == environment.detect_platform():
        pytest.skip("the running system")
    env = {"USERPROFILE": r"C:\Users\Alice", "OneDrive": r"C:\Users\Alice\OneDrive"}
    # [0015.20] a home as the context's system writes it, on Windows too
    context = environment.default_context(
        platform=platform, env=env, home=PurePosixPath("/home/alice")
    )
    assert isinstance(context.synced, NoSyncedFolders)


def test_on_windows_the_context_reads_the_environment_it_was_given(tmp_path: Path) -> None:
    # [0017.10]
    if environment.detect_platform() != "windows":
        pytest.skip("Windows only")
    env = {"USERPROFILE": str(tmp_path), "OneDrive": str(tmp_path / "OneDrive")}
    context = environment.default_context(env=env)
    assert PureWindowsPath(tmp_path / "OneDrive") in context.synced.folders()
