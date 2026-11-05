"""Sessions: what keeps a sign-in, a saved password or the open tabs, never touched.

The list is data (``core/sessions.toml``); the policy blocks each with a reason of its own,
``session`` (decision 0020, item 13). Patterns are names one inside the other that end a path
anywhere, ``*`` and ``?`` matching within one name.
"""

import re
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

import pytest

from fakes import FakeOpenFiles
from kresorter.core.heuristics import JunkClassifier, Platform, default_rules
from kresorter.core.models import FileEntry, Skipped, SkipReason
from kresorter.core.policy import BlockReason, PathPolicy, Verdict
from kresorter.core.sessions import (
    Session,
    SessionPaths,
    default_sessions,
    load_sessions,
    session_patterns,
)
from kresorter.core.walker import walk

SESSION = Verdict(allowed=False, reason=BlockReason.SESSION)
ALLOWED = Verdict(allowed=True, reason=None)

WIN = PathPolicy.for_windows(
    {
        "SystemDrive": "C:",
        "SystemRoot": r"C:\Windows",
        "ProgramFiles": r"C:\Program Files",
        "ProgramData": r"C:\ProgramData",
        "USERPROFILE": r"C:\Users\Alice",
    }
)
LINUX = PathPolicy.for_posix(home=PurePosixPath("/home/alice"), platform="linux")
MAC = PathPolicy.for_posix(home=PurePosixPath("/Users/alice"), platform="darwin")

LOCAL = r"C:\Users\Alice\AppData\Local"
CHROME = LOCAL + r"\Google\Chrome\User Data\Default"

# Every under and every path of every session, in an example (enforced below), where nothing
# else blocks it: on Windows outside AppData\Roaming, in a home outside its .ssh and .gnupg.
EXAMPLES: dict[str, list[str]] = {
    "chromium-profile": [
        CHROME + r"\Network\Cookies",
        CHROME + r"\Cookies",
        CHROME + r"\Cookies-journal",
        CHROME + r"\Extension Cookies",
        CHROME + r"\Login Data For Account-journal",
        CHROME + r"\Web Data",
        CHROME + r"\Account Web Data",
        LOCAL + r"\Yandex\YandexBrowser\User Data\Default\Ya Passman Data",
        LOCAL + r"\Yandex\YandexBrowser\User Data\Profile 1\Ya Credit Cards",
        LOCAL + r"\Microsoft\Edge\User Data\Default\Local Storage\leveldb\000003.log",
        LOCAL + r"\BraveSoftware\Brave-Browser\User Data\Default\Session Storage\LOG",
        LOCAL + r"\Vivaldi\User Data\Default\Sessions\Tabs_13350000000000000",
        LOCAL + r"\Chromium\User Data\Default\Current Session",
        LOCAL + r"\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams\EBWebView"
        r"\Default\Current Tabs",
        r"D:\Backup\Opera Software\Opera Stable\Last Session",
        "/home/alice/snap/chromium/common/chromium/Default/Last Tabs",
        "/home/alice/.config/BraveSoftware/Brave-Browser/Default/IndexedDB/x.leveldb/LOG",
        "/home/alice/.config/discord/Service Worker/Database/LOG",
        "/home/alice/.config/google-chrome/Default/WebStorage/QuotaManager",
        "/home/alice/.var/app/com.slack.Slack/config/Slack/Storage/ext",
        "/home/alice/.var/app/org.chromium.Chromium/config/chromium/Default/databases/x",
        "/Users/alice/Library/Application Support/Signal/File System/000/p",
        "/Users/alice/Library/Application Support/Vivaldi/Default/Extensions/x/1.0/m.json",
        "/Users/alice/Library/Application Support/Google/Chrome/Profile 2"
        "/Local Extension Settings/x/LOG",
        CHROME + r"\Sync Extension Settings\x\LOG",
        CHROME + r"\Extension State\LOG",
        CHROME + r"\Sync Data\LevelDB\LOG",
        CHROME + r"\Preferences",
        CHROME + r"\Secure Preferences",
        CHROME + r"\Bookmarks.bak",
        CHROME + r"\History-journal",
    ],
    "chromium-local-state": [
        LOCAL + r"\Google\Chrome\User Data\Local State",
        "/home/alice/.config/opera/Local State",
    ],
    "firefox-profile": [
        "/Users/alice/Library/Application Support/Firefox/Profiles/x.default/cookies.sqlite-wal",
        "/home/alice/.mozilla/firefox/x.default-release/logins-backup.json",
        "/Users/alice/Library/Thunderbird/Profiles/x.default/key4.db",
        "/home/alice/.thunderbird/x.default/key3.db",
        "/Users/alice/Library/Application Support/LibreWolf/Profiles/x/cert9.db",
        "/home/alice/.librewolf/x.default/signedInUser.json",
        "/Users/alice/Library/Application Support/Waterfox/Profiles/x/places.sqlite",
        "/home/alice/.waterfox/x/formhistory.sqlite",
        "/home/alice/.mozilla/firefox/x/permissions.sqlite",
        "/home/alice/.mozilla/firefox/x/sessionstore-backups/recovery.jsonlz4",
        "/home/alice/.mozilla/firefox/x/containers.json",
        "/home/alice/.mozilla/firefox/x/storage/default/https+++example.org/ls/data.sqlite",
        "/home/alice/.mozilla/firefox/x/webappsstore.sqlite",
        "/home/alice/.mozilla/firefox/x/prefs.js",
        "/home/alice/.mozilla/firefox/x/extensions.json",
    ],
    "windows-sign-in": [
        LOCAL + r"\Microsoft\Windows\INetCookies\ESE\container.dat",
        LOCAL + r"\Packages\Microsoft.Windows.Photos_8wekyb3d8bbwe\AC\INetCookies\x.cookie",
        r"D:\Backup\Alice\AppData\Roaming\Microsoft\Windows\Cookies\index.dat",
        LOCAL + r"\Microsoft\Windows\WebCache\WebCacheV01.dat",
        LOCAL + r"\Microsoft\Credentials\DFBE70A7E5CC19A398EBF1B96859CE5D",
        r"D:\Backup\Alice\AppData\Roaming\Microsoft\Protect\S-1-5-21\key",
        LOCAL + r"\Microsoft\Vault\4BF4C442-9B8A-41A0-B380-DD4A704DDB28\Policy.vpol",
        r"D:\Backup\Alice\AppData\Roaming\Microsoft\Crypto\Keys\x",
        LOCAL + r"\Microsoft\TokenBroker\Cache\x.tbres",
        LOCAL + r"\Microsoft\IdentityCache\x",
        LOCAL + r"\Microsoft\OneAuth\accounts\x",
        LOCAL + r"\Packages\Microsoft.AAD.BrokerPlugin_cw5n1h2txyewy\AC\TokenBroker\x.tbacct",
    ],
    "macos-sign-in": [
        "/Users/alice/Library/Keychains/login.keychain-db",
        "/Users/alice/Library/Accounts/Accounts4.sqlite",
        "/Users/alice/Library/Containers/com.apple.Safari/Data/Library/Cookies/x.binarycookies",
        "/Users/alice/Library/HTTPStorages/com.apple.Safari",
        "/Users/alice/Library/Safari/LastSession.plist",
    ],
    "linux-sign-in": [
        "/home/alice/.local/share/keyrings/login.keyring",
        "/home/alice/.local/share/kwalletd/kdewallet.kwl",
        "/home/alice/.password-store/mail.gpg",
        "/home/alice/.pki/nssdb/cert9.db",
    ],
    "telegram": [
        r"D:\Telegram\tdata\key_datas",
        "/home/alice/.local/share/TelegramDesktop/tdata/D877F783D5D3EF8C/maps",
    ],
    "game-launchers": [
        r"D:\Games\Steam\config\loginusers.vdf",
        "/home/alice/.steam/debian-installation/config/config.vdf",
        LOCAL + r"\Steam\local.vdf",
        r"D:\Games\Steam\ssfn1234567890",
        LOCAL + r"\EpicGamesLauncher\Saved\Config\Windows\GameUserSettings.ini",
    ],
    "keys-and-tokens": [
        r"C:\Users\Alice\.ssh\id_ed25519",
        r"C:\Users\Alice\.gnupg\pubring.kbx",
        r"C:\Users\Alice\.aws\credentials",
        "/home/alice/.aws/sso/cache/x.json",
        "/home/alice/.azure/msal_token_cache.json",
        "/home/alice/.config/gcloud/credentials.db",
        r"C:\Users\Alice\.docker\config.json",
        "/home/alice/.kube/config",
        "/home/alice/.netrc",
        r"C:\Users\Alice\_netrc",
        "/Users/alice/.git-credentials",
        "/home/alice/.config/gh/hosts.yml",
        r"D:\Backup\Alice\AppData\Roaming\GitHub CLI\hosts.yml",
        "/home/alice/.cache/huggingface/token",
        r"C:\Users\Alice\.cache\huggingface\stored_tokens",
    ],
}

WINDOWS_PATH = re.compile(r"[A-Z]:\\")


def system_of(example: str) -> tuple[PathPolicy, PurePath, bool]:
    """The policy of the system the example is a path of, the path, and if it folds case."""
    if WINDOWS_PATH.match(example):
        return WIN, PureWindowsPath(example), True
    if example.startswith("/Users/"):
        return MAC, PurePosixPath(example), True
    return LINUX, PurePosixPath(example), False


def holds(patterns: tuple[str, ...], example: str) -> bool:
    _, path, folds = system_of(example)
    fold = str.casefold if folds else str
    return SessionPaths(patterns, fold).holds(tuple(fold(name) for name in path.parts[1:]))


SESSIONS = {session.id: session for session in default_sessions()}


def test_every_session_has_its_examples() -> None:
    # [0020.13] each entry with an example a test checks
    assert set(EXAMPLES) == set(SESSIONS)


@pytest.mark.parametrize(
    ("session", "example"),
    [(session, example) for session, examples in EXAMPLES.items() for example in examples],
)
def test_every_example_is_its_session_s_and_blocked_as_one(session: str, example: str) -> None:
    # [0020.13] never a candidate, a reason of its own
    assert holds(SESSIONS[session].patterns, example)
    policy, path, _ = system_of(example)
    assert policy.check_path(path) == SESSION


@pytest.mark.parametrize("session", sorted(EXAMPLES))
def test_every_path_and_every_under_has_an_example(session: str) -> None:
    # [0020.13] each in an example of its own session
    entry = SESSIONS[session]
    examples = EXAMPLES[session]
    unders = entry.under or ("",)

    def join(under: str, path: str) -> str:
        return f"{under}/{path}" if under else path

    for path in entry.paths:
        patterns = tuple(join(under, path) for under in unders)
        assert any(holds(patterns, example) for example in examples), path
    for under in entry.under:
        patterns = tuple(join(under, path) for path in entry.paths)
        assert any(holds(patterns, example) for example in examples), under


@pytest.mark.parametrize(
    "example",
    [
        # [0020.13] a browser's cache is junk of its own beside its sessions, for review
        CHROME + r"\Cache\Cache_Data\data_0",
        CHROME + r"\Code Cache\js\index",
        CHROME + r"\GPUCache\data_1",
        LOCAL + r"\Mozilla\Firefox\Profiles\x.default\cache2\entries\A1",
        LOCAL + r"\Microsoft\Windows\INetCache\IE\x.dat",
        "/home/alice/.cache/google-chrome/Default/Cache/Cache_Data/data_0",
        "/home/alice/.cache/mozilla/firefox/x.default/cache2/entries/A1",
        "/Users/alice/Library/Caches/Google/Chrome/Default/Cache/Cache_Data/data_0",
    ],
)
def test_a_browser_s_cache_stays_junk(example: str) -> None:
    policy, path, _ = system_of(example)
    platform: Platform = "windows" if policy is WIN else "darwin" if policy is MAC else "linux"
    assert policy.check_path(path) == ALLOWED
    assert JunkClassifier(default_rules(), platform=platform).classify(path) is not None


@pytest.mark.parametrize(
    "example",
    [
        # [0020.13] a name of a session elsewhere is no session
        r"C:\Users\Alice\Downloads\Cookies.txt",
        r"C:\Users\Alice\Downloads\Cookies recipe.pdf",
        r"C:\Users\Alice\Documents\History\essay.docx",
        r"C:\Users\Alice\Documents\Network\plan.vsdx",
        r"C:\Users\Alice\Documents\Preferences",
        CHROME + r"\Visited Links",
        "/home/alice/Documents/Storage/box.jpg",
        "/home/alice/.config/google-chrome/Default/Cookies.png",
        "/home/alice/.config/Network",
        "/home/alice/.config/app/sub/deeper/Cookies",
        "/home/alice/.mozilla/firefox/x/key10.db",
        "/home/alice/.mozilla/firefox/x/cache2/x",
        "/home/alice/projects/telegram-bot/data/x.json",
        "/home/alice/Steam/configs.txt",
        "/home/alice/.aws/config",
        "/home/alice/huggingface/tokenizer.json",
    ],
)
def test_a_name_of_a_session_elsewhere_is_allowed(example: str) -> None:
    policy, path, _ = system_of(example)
    assert policy.check_path(path) == ALLOWED


def test_a_session_is_blocked_even_named_by_hand_its_open_check_never_asked() -> None:
    # [0020.13] like a system file: check_file says so before any open-file check
    open_files = FakeOpenFiles()
    assert WIN.check_file(PureWindowsPath(CHROME + r"\Login Data"), open_files) == SESSION
    assert open_files.calls == []


def test_what_blocks_first_says_so() -> None:
    # [0020.13] a session in a folder blocked anyway keeps the folder's reason
    roaming = r"C:\Users\Alice\AppData\Roaming\Mozilla\Firefox\Profiles\x\logins.json"
    assert WIN.check_path(PureWindowsPath(roaming)).reason == BlockReason.PROFILE
    assert LINUX.check_path(PurePosixPath("/home/alice/.ssh/id_rsa")).reason == (
        BlockReason.PROFILE
    )
    assert LINUX.check_path(PurePosixPath("/usr/share/keyrings/x.gpg")).reason == (
        BlockReason.SYSTEM
    )


def test_case_counts_on_linux_only() -> None:
    # names compare as each system compares them
    assert MAC.check_path(PurePosixPath("/Users/alice/library/KEYCHAINS/x")) == SESSION
    assert LINUX.check_path(PurePosixPath("/home/alice/.mozilla/firefox/x/LOGINS.JSON")) == (
        ALLOWED
    )
    upper = r"C:\USERS\ALICE\APPDATA\LOCAL\GOOGLE\CHROME\USER DATA\DEFAULT\COOKIES"
    assert WIN.check_path(PureWindowsPath(upper)) == SESSION


def test_the_walker_leaves_a_profile_s_sessions_out_and_lists_its_cache(tmp_path: Path) -> None:
    # [0020.13] its folders are not listed; a file of a session is skipped, blocked
    home = tmp_path / "home"
    profile = home / ".config" / "google-chrome" / "Default"
    tdata = home / ".local" / "share" / "TelegramDesktop" / "tdata"
    for path in (
        profile / "Network" / "Cookies",
        profile / "Cookies-journal",
        profile / "Preferences",
        profile / "GPUCache" / "data_0",
        profile / "Visited Links",
        tdata / "key_datas",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    policy = PathPolicy.for_posix(home=PurePosixPath(home), platform="linux")
    events = list(walk([home], policy))

    assert sorted(e.path for e in events if isinstance(e, FileEntry)) == [
        profile / "GPUCache" / "data_0",
        profile / "Visited Links",
    ]
    skipped = [(e.path, e.reason, e.block_reason) for e in events if isinstance(e, Skipped)]
    assert sorted(skipped) == [
        (path, SkipReason.BLOCKED, BlockReason.SESSION)
        for path in sorted(
            [profile / "Cookies-journal", profile / "Network", profile / "Preferences", tdata]
        )
    ]


# --- the patterns' names -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("patterns", "names", "expected"),
    [
        (["a/b"], ("a", "b"), True),
        (["a/b"], ("x", "a", "b"), True),
        (["a/b"], ("a", "b", "c", "d"), True),  # inside it
        (["a/b"], ("a", "x", "b"), False),
        (["a/b"], ("b",), False),
        (["a/b"], ("a",), False),
        (["a/b"], (), False),
        (["a/*/c"], ("a", "x", "c"), True),
        (["a/*/c"], ("a", "c"), False),
        (["a/*/c"], ("a", "x", "y", "c"), False),  # within one name
        (["p/key?.db"], ("p", "key4.db"), True),
        (["p/key?.db"], ("p", "key10.db"), False),
        (["x/Cookies*", "x/y"], ("Cookies-journal",), False),
        (["x/Cookies*", "x/y"], ("x", "Cookies-journal"), True),
        (["a/b*"], ("a", "b-journal"), True),
        (["a/b*"], ("a", "x", "b"), False),
        (["a/b", "c/d/e"], ("c", "d", "e"), True),
        (["a/b", "c/d/e"], ("c", "x", "e"), False),
        (["a\nb/c"], ("a\nb", "c"), True),
    ],
)
def test_a_pattern_ends_a_path_anywhere_or_holds_it(
    patterns: list[str], names: tuple[str, ...], expected: bool
) -> None:
    assert SessionPaths(patterns, str).holds(names) is expected


@pytest.mark.parametrize("pattern", ["*", "*/?", "b*", "a?/[bc]"])
def test_a_pattern_writes_out_a_name_in_full(pattern: str) -> None:
    # by it a pattern is found, not tried on every path
    with pytest.raises(ValueError, match=re.escape(f"{pattern!r} writes out no name in full")):
        SessionPaths(["a/b", pattern], str)


def test_patterns_are_folded_as_names_are() -> None:
    assert SessionPaths(["Local State"], str.casefold).holds(("local state",))
    assert not SessionPaths(["Local State"], str).holds(("local state",))


DIRECTORIES = [(), ("a",), ("x", "a"), ("a", "x"), ("a", "x", "c"), ("q", "a", "b"), ("q",)]
NAMES = ["a", "b", "c", "b-x", "key4.db", "key10.db", "d"]


@pytest.mark.parametrize("directory", DIRECTORIES)
def test_a_name_in_a_directory_is_asked_as_its_path_is(directory: tuple[str, ...]) -> None:
    # [0018.14] the directory once, then each name alone
    paths = SessionPaths(["a/b", "a/*/c", "x/a/b*", "q/key?.db", "a/x/c/d", "d"], str)
    ends = paths.names_in(directory)
    for name in NAMES:
        if not paths.holds(directory):
            assert ends(name) is paths.holds((*directory, name)), name


def test_without_patterns_nothing_is_held() -> None:
    paths = SessionPaths([], str)
    assert not paths.holds(("a", "b"))
    assert not paths.names_in(("a",))("b")


# --- the data ------------------------------------------------------------------------------------


def test_the_shipped_sessions_load_and_join_their_paths_under_their_unders() -> None:
    sessions = default_sessions()
    assert [s.id for s in sessions][:2] == ["chromium-profile", "chromium-local-state"]
    assert "User Data/*/Network" in sessions[0].patterns
    assert sessions[1].patterns == ("Local State",)
    assert set(session_patterns()) == {p for s in sessions for p in s.patterns}


def test_a_session_reads_from_toml() -> None:
    text = """
[[session]]
id = "a"
what = "A"
under = ["u", "v/*"]
paths = ["p", "q/r"]

[[session]]
id = "b"
what = "B"
paths = ["x"]
"""
    assert load_sessions(text) == (
        Session("a", "A", ("u", "v/*"), ("p", "q/r")),
        Session("b", "B", (), ("x",)),
    )
    assert load_sessions(text)[0].patterns == ("u/p", "u/q/r", "v/*/p", "v/*/q/r")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "expected [[session]] tables"),
        ("session = 1", "expected [[session]] tables"),
        ('[[session]]\nwhat = "w"\npaths = ["p"]', "session #1: missing required key 'id'"),
        ('[[session]]\nid = "a"\npaths = ["p"]', "session #1: missing required key 'what'"),
        ('[[session]]\nid = 1\nwhat = "w"', "session #1: missing required key 'id'"),
        ('[[session]]\nid = "a"\nwhat = "w"', "session 'a': needs paths"),
        ('[[session]]\nid = "a"\nwhat = "w"\npaths = []', "session 'a': needs paths"),
        (
            '[[session]]\nid = "a"\nwhat = "w"\npaths = "p"',
            "session 'a': 'paths' must be a list of strings",
        ),
        (
            '[[session]]\nid = "a"\nwhat = "w"\npaths = ["p"]\nunder = [1]',
            "session 'a': 'under' must be a list of strings",
        ),
        (
            '[[session]]\nid = "a"\nwhat = "w"\npaths = ["p"]\nplatforms = ["linux"]',
            "session 'a': unknown key 'platforms'",
        ),
        (
            '[[session]]\nid = "a"\nwhat = "w"\npaths = ["p"]\n'
            '[[session]]\nid = "a"\nwhat = "w"\npaths = ["q"]',
            "duplicate session id 'a'",
        ),
    ],
)
def test_a_wrong_table_is_named(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        load_sessions(text)


@pytest.mark.parametrize(
    ("paths", "under", "message"),
    [
        (["a//b"], [], "'a//b' is no names one inside the other"),
        (["/a"], [], "'/a' is no names one inside the other"),
        (["a/"], [], "'a/' is no names one inside the other"),
        (["a/../b"], [], "'a/../b' is no names one inside the other"),
        (["./a"], [], "'./a' is no names one inside the other"),
        (["a\\\\b"], [], "'a\\\\b' is no names one inside the other"),
        (["p"], ["u//v"], "'u//v' is no names one inside the other"),
        (["*"], [], "'*' writes out no name in full"),
        (["*/x?"], [], "'*/x?' writes out no name in full"),
        (["p", "[ab]*"], [], "'[ab]*' writes out no name in full"),
        (["p*"], ["u", "*"], "'*/p*' writes out no name in full"),
    ],
)
def test_a_wrong_path_is_named(paths: list[str], under: list[str], message: str) -> None:
    def strings(values: list[str]) -> str:
        return "[" + ", ".join(f'"{v}"' for v in values) + "]"

    text = f'[[session]]\nid = "a"\nwhat = "w"\npaths = {strings(paths)}\nunder = {strings(under)}'
    with pytest.raises(ValueError, match=re.escape(f"session 'a': {message}")):
        load_sessions(text)
