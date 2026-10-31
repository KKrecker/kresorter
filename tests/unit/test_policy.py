"""Path policy: hard blacklist (never touch) and default safe zones (scan when nothing is chosen).

Windows cases run on any OS via PureWindowsPath; the policy never touches the filesystem.
Symlink resolution is the walker's job, so symlink cases live in test_walker.py.
"""

from pathlib import PurePath, PurePosixPath, PureWindowsPath

import pytest

from fakes import BrokenOpenFiles, FakeOpenFiles
from safeclean.core.policy import BlockReason, PathPolicy, Verdict

WIN_ENV = {
    "SystemDrive": "C:",
    "SystemRoot": r"C:\Windows",
    "ProgramFiles": r"C:\Program Files",
    "ProgramFiles(x86)": r"C:\Program Files (x86)",
    "ProgramData": r"C:\ProgramData",
    "USERPROFILE": r"C:\Users\Alice",
}


@pytest.fixture
def win() -> PathPolicy:
    return PathPolicy.for_windows(WIN_ENV)


@pytest.fixture
def linux() -> PathPolicy:
    return PathPolicy.for_posix(home=PurePosixPath("/home/alice"), platform="linux")


@pytest.fixture
def mac() -> PathPolicy:
    return PathPolicy.for_posix(home=PurePosixPath("/Users/alice"), platform="darwin")


def blocked(reason: BlockReason) -> Verdict:
    return Verdict(allowed=False, reason=reason)


ALLOWED = Verdict(allowed=True, reason=None)


# --- Windows blacklist -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(r"C:\Program Files\App\a.dll", blocked(BlockReason.PROGRAM_FILES), id="pf"),
        pytest.param(
            r"C:\Program Files (x86)\App\a.dll", blocked(BlockReason.PROGRAM_FILES), id="pf-x86"
        ),
        pytest.param(r"c:\PROGRAM FILES\app\a.dll", blocked(BlockReason.PROGRAM_FILES), id="case"),
        pytest.param(r"C:\Program Files", blocked(BlockReason.PROGRAM_FILES), id="pf-root"),
        pytest.param(
            r"C:\Temp\..\Program Files\a.dll", blocked(BlockReason.PROGRAM_FILES), id="dotdot"
        ),
        pytest.param(
            r"C:\..\..\Program Files\a.dll", blocked(BlockReason.PROGRAM_FILES), id="dotdot-root"
        ),
        pytest.param(r"C:\Program Files Backup\a.txt", ALLOWED, id="similar-prefix"),
        pytest.param(r"C:\Windows\System32\x.dll", blocked(BlockReason.SYSTEM), id="windows"),
        pytest.param(r"C:\ProgramData\Vendor\cfg.ini", blocked(BlockReason.SYSTEM), id="pdata"),
        pytest.param(r"C:\pagefile.sys", blocked(BlockReason.SYSTEM), id="pagefile"),
        pytest.param(r"C:\$Recycle.Bin\S-1\x", blocked(BlockReason.SYSTEM), id="recycle-bin"),
        pytest.param(
            r"C:\Users\Bob\Documents\a.txt", blocked(BlockReason.PROFILE), id="other-user"
        ),
        pytest.param(r"C:\Users\Public\a.txt", blocked(BlockReason.PROFILE), id="public"),
        pytest.param(r"C:\Users\Alice\NTUSER.DAT", blocked(BlockReason.PROFILE), id="ntuser"),
        pytest.param(r"C:\Users\Alice\ntuser.dat.LOG1", blocked(BlockReason.PROFILE), id="ntlog"),
        pytest.param(
            r"C:\Users\Alice\AppData\Local\Microsoft\Windows\UsrClass.dat",
            blocked(BlockReason.PROFILE),
            id="usrclass",
        ),
        pytest.param(
            r"C:\Users\Alice\AppData\Roaming\App\cfg", blocked(BlockReason.PROFILE), id="roaming"
        ),
        pytest.param(r"C:\Users\Alice\Downloads\setup.exe", ALLOWED, id="own-downloads"),
        # Temp: not blacklisted, only absent from default roots (decision 0002).
        pytest.param(r"C:\Users\Alice\AppData\Local\Temp\a.tmp", ALLOWED, id="temp-explicit"),
    ],
)
def test_windows_blacklist(win: PathPolicy, path: str, expected: Verdict) -> None:
    assert win.check_path(PureWindowsPath(path)) == expected


def test_program_files_taken_from_environment() -> None:
    policy = PathPolicy.for_windows({**WIN_ENV, "ProgramFiles": r"D:\Apps"})

    assert policy.check_path(PureWindowsPath(r"D:\Apps\x.exe")) == blocked(
        BlockReason.PROGRAM_FILES
    )
    # Defaults stay blocked even when the environment points elsewhere (fail closed).
    assert policy.check_path(PureWindowsPath(r"C:\Program Files\x.exe")) == blocked(
        BlockReason.PROGRAM_FILES
    )


# --- POSIX blacklist ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("/usr/lib/libc.so", blocked(BlockReason.SYSTEM), id="usr"),
        pytest.param("/etc/passwd", blocked(BlockReason.SYSTEM), id="etc"),
        pytest.param("/proc/1/maps", blocked(BlockReason.SYSTEM), id="proc"),
        pytest.param("/sys/kernel", blocked(BlockReason.SYSTEM), id="sys"),
        pytest.param("/dev/sda", blocked(BlockReason.SYSTEM), id="dev"),
        pytest.param("/opt/app/bin", blocked(BlockReason.PROGRAM_FILES), id="opt"),
        pytest.param("/usrlocal-backup/a", ALLOWED, id="similar-prefix"),
        pytest.param("/home/bob/a.txt", blocked(BlockReason.PROFILE), id="other-user"),
        pytest.param("/home/alice/.ssh/id_ed25519", blocked(BlockReason.PROFILE), id="ssh"),
        pytest.param("/home/alice/.gnupg/pubring.kbx", blocked(BlockReason.PROFILE), id="gnupg"),
        pytest.param("/home/alice/.cache/pip/x", ALLOWED, id="cache"),
        pytest.param("/tmp/a.tmp", ALLOWED, id="tmp-explicit"),
    ],
)
def test_linux_blacklist(linux: PathPolicy, path: str, expected: Verdict) -> None:
    assert linux.check_path(PurePosixPath(path)) == expected


def test_linux_is_case_sensitive(linux: PathPolicy) -> None:
    assert linux.check_path(PurePosixPath("/USR/a")) == ALLOWED


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("/System/Library/x", blocked(BlockReason.SYSTEM), id="system"),
        # APFS is case-insensitive by default: treat macOS paths case-insensitively.
        pytest.param("/system/library/x", blocked(BlockReason.SYSTEM), id="system-lower"),
        pytest.param("/Library/Preferences/x", blocked(BlockReason.SYSTEM), id="library"),
        pytest.param("/Applications/App.app", blocked(BlockReason.PROGRAM_FILES), id="apps"),
        pytest.param("/Users/bob/a.txt", blocked(BlockReason.PROFILE), id="other-user"),
        pytest.param("/Users/alice/.ssh/config", blocked(BlockReason.PROFILE), id="ssh"),
        pytest.param("/Users/alice/Downloads/a.dmg", ALLOWED, id="downloads"),
    ],
)
def test_macos_blacklist(mac: PathPolicy, path: str, expected: Verdict) -> None:
    assert mac.check_path(PurePosixPath(path)) == expected


# --- input validation --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("policy_name", "path"),
    [
        pytest.param("win", PureWindowsPath(r"a\b.txt"), id="win-relative"),
        pytest.param("win", PureWindowsPath(r"\no\drive.txt"), id="win-no-drive"),
        pytest.param("linux", PurePosixPath("a/b.txt"), id="posix-relative"),
    ],
)
def test_relative_path_is_rejected(
    win: PathPolicy, linux: PathPolicy, policy_name: str, path: PurePath
) -> None:
    policy = {"win": win, "linux": linux}[policy_name]
    with pytest.raises(ValueError, match="absolute"):
        policy.check_path(path)


# --- open files (check_file = blacklist + open-file check) ------------------------------------


def test_open_file_is_blocked(linux: PathPolicy) -> None:
    path = PurePosixPath("/home/alice/Downloads/movie.mkv")

    assert linux.check_file(path, FakeOpenFiles([path])) == blocked(BlockReason.OPEN_FILE)


def test_closed_file_is_allowed(linux: PathPolicy) -> None:
    path = PurePosixPath("/home/alice/Downloads/movie.mkv")

    assert linux.check_file(path, FakeOpenFiles()) == ALLOWED


def test_open_file_check_failure_blocks(linux: PathPolicy) -> None:
    path = PurePosixPath("/home/alice/Downloads/movie.mkv")

    assert linux.check_file(path, BrokenOpenFiles()) == blocked(BlockReason.OPEN_FILE)


def test_blacklisted_file_skips_open_check(linux: PathPolicy) -> None:
    checker = FakeOpenFiles()

    assert linux.check_file(PurePosixPath("/etc/passwd"), checker) == blocked(BlockReason.SYSTEM)
    assert checker.calls == []


# --- app data directory: vault and journal are never candidates (decision 0004) ----------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(
            "/home/alice/.local/share/safeclean/quarantine/1/2",
            blocked(BlockReason.APP_DATA),
            id="vault",
        ),
        pytest.param(
            "/home/alice/.local/share/safeclean/journal.db",
            blocked(BlockReason.APP_DATA),
            id="journal",
        ),
        pytest.param(
            "/home/alice/.local/share/safeclean", blocked(BlockReason.APP_DATA), id="dir-itself"
        ),
        pytest.param("/home/alice/.local/share/other/a", ALLOWED, id="sibling-app"),
        pytest.param("/home/alice/.local/share/safeclean-old/a", ALLOWED, id="name-prefix-only"),
    ],
)
def test_linux_app_data_is_blocked(linux: PathPolicy, path: str, expected: Verdict) -> None:
    assert linux.check_path(PurePosixPath(path)) == expected


def test_linux_app_data_follows_xdg_data_home() -> None:
    policy = PathPolicy.for_posix(
        home=PurePosixPath("/home/alice"), platform="linux", env={"XDG_DATA_HOME": "/data/xdg"}
    )
    assert policy.app_data_dir == PurePosixPath("/data/xdg/safeclean")
    assert policy.check_path(PurePosixPath("/data/xdg/safeclean/q")) == blocked(
        BlockReason.APP_DATA
    )


@pytest.mark.parametrize("value", ["", "relative/share"])
def test_linux_ignores_empty_or_relative_xdg_data_home(value: str) -> None:
    # XDG Base Directory spec: relative paths are invalid and must be ignored.
    policy = PathPolicy.for_posix(
        home=PurePosixPath("/home/alice"), platform="linux", env={"XDG_DATA_HOME": value}
    )
    assert policy.app_data_dir == PurePosixPath("/home/alice/.local/share/safeclean")


def test_app_data_inside_a_default_root_is_still_blocked() -> None:
    # A custom XDG_DATA_HOME under ~/.cache must not expose the vault as junk.
    policy = PathPolicy.for_posix(
        home=PurePosixPath("/home/alice"),
        platform="linux",
        env={"XDG_DATA_HOME": "/home/alice/.cache/xdg"},
    )
    assert policy.check_path(PurePosixPath("/home/alice/.cache/xdg/safeclean/q/1")) == blocked(
        BlockReason.APP_DATA
    )
    assert policy.check_path(PurePosixPath("/home/alice/.cache/other")) == ALLOWED


def test_macos_app_data_is_blocked_case_insensitively(mac: PathPolicy) -> None:
    assert mac.app_data_dir == PurePosixPath("/Users/alice/Library/Application Support/safeclean")
    for path in (
        "/Users/alice/Library/Application Support/safeclean/q",
        "/users/ALICE/library/application support/SafeClean/q",
    ):
        assert mac.check_path(PurePosixPath(path)) == blocked(BlockReason.APP_DATA)


def test_windows_app_data_uses_localappdata() -> None:
    policy = PathPolicy.for_windows({**WIN_ENV, "LOCALAPPDATA": r"D:\Local"})
    assert policy.app_data_dir == PureWindowsPath(r"D:\Local\safeclean")
    assert policy.check_path(PureWindowsPath(r"d:\LOCAL\SafeClean\q")) == blocked(
        BlockReason.APP_DATA
    )


def test_windows_app_data_falls_back_to_profile(win: PathPolicy) -> None:
    assert win.app_data_dir == PureWindowsPath(r"C:\Users\Alice\AppData\Local\safeclean")
    assert win.check_path(PureWindowsPath(r"C:\Users\Alice\AppData\Local\safeclean\q")) == (
        blocked(BlockReason.APP_DATA)
    )
    assert win.check_path(PureWindowsPath(r"C:\Users\Alice\AppData\Local\Other\a")) == ALLOWED


def test_linux_default_data_dir_stays_blocked_under_custom_xdg() -> None:
    # A vault left at the default location before XDG_DATA_HOME changed must stay invisible.
    policy = PathPolicy.for_posix(
        home=PurePosixPath("/home/alice"), platform="linux", env={"XDG_DATA_HOME": "/data/xdg"}
    )
    assert policy.app_data_dir == PurePosixPath("/data/xdg/safeclean")
    assert policy.check_path(PurePosixPath("/home/alice/.local/share/safeclean/q")) == blocked(
        BlockReason.APP_DATA
    )


def test_windows_default_data_dir_stays_blocked_under_custom_localappdata() -> None:
    policy = PathPolicy.for_windows({**WIN_ENV, "LOCALAPPDATA": r"D:\Local"})
    assert policy.app_data_dir == PureWindowsPath(r"D:\Local\safeclean")
    assert policy.check_path(PureWindowsPath(r"C:\Users\Alice\AppData\Local\safeclean\q")) == (
        blocked(BlockReason.APP_DATA)
    )


def test_app_data_skips_the_open_file_check(linux: PathPolicy) -> None:
    checker = FakeOpenFiles()
    path = PurePosixPath("/home/alice/.local/share/safeclean/journal.db")
    assert linux.check_file(path, checker) == blocked(BlockReason.APP_DATA)
    assert checker.calls == []


# --- default safe zones (decision 0002) --------------------------------------------------------


def test_linux_default_roots_are_cache_and_downloads(linux: PathPolicy) -> None:
    assert linux.default_roots() == (
        PurePosixPath("/home/alice/.cache"),
        PurePosixPath("/home/alice/Downloads"),
    )


def test_windows_default_roots_exclude_temp(win: PathPolicy) -> None:
    assert win.default_roots() == (
        PureWindowsPath(r"C:\Users\Alice\.cache"),
        PureWindowsPath(r"C:\Users\Alice\Downloads"),
    )
