"""Reading macOS LaunchAgents and LaunchDaemons (step 4, commit 9; decision 0011).

Every ``*.plist`` in ``~/Library/LaunchAgents`` (user), ``/Library/LaunchAgents`` and
``/Library/LaunchDaemons`` (system) is loaded by launchd at login or boot, so each is an item;
``RunAtLoad`` and ``KeepAlive`` say whether it also starts then. ``/System/Library`` (the OS,
protected by SIP) is not read. The state is the file's ``Disabled`` key; the overrides launchd
keeps of its own are not read, so every item says ``state from the file``. XML and binary
property lists; read-only.
"""

import plistlib
from pathlib import Path

import pytest

from kresorter.autostart.entries import MAX_ENTRY_BYTES
from kresorter.autostart.launchd import launchd_dirs, read_launchd
from kresorter.autostart.models import (
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
    entry_digest,
)
from support.host import cannot_list, make_fifo

Dirs = tuple[Path, Path, Path]
Content = dict[str, object] | list[object] | bytes  # a property list to write, or raw bytes

INVALID = "not a valid property list"
FROM_FILE = "state from the file"  # launchd's own overrides are not read (0011, item 40)
AGENT: dict[str, object] = {
    "Label": "com.example.sync",
    "ProgramArguments": ["/Applications/Sync.app/Contents/MacOS/sync", "--tray", "a b"],
    "RunAtLoad": True,
}


def plist(directory: Path, name: str, content: Content = AGENT, *, binary: bool = False) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    form = plistlib.FMT_BINARY if binary else plistlib.FMT_XML
    path.write_bytes(content if isinstance(content, bytes) else plistlib.dumps(content, fmt=form))
    return path


def xml_plist(body: str) -> bytes:
    """A broken XML property list: ``plistlib`` fails on it in its own ways."""
    return f'<?xml version="1.0"?><plist><dict>{body}</dict></plist>'.encode()


def agent(**keys: object) -> dict[str, object]:
    return {k: v for k, v in {**AGENT, **keys}.items() if v is not None}


@pytest.fixture
def dirs(tmp_path: Path) -> Dirs:
    return launchd_dirs(tmp_path / "Users" / "me", tmp_path)


def read(dirs: Dirs) -> AutostartListing:
    return read_launchd(*dirs)


def skip(path: Path, detail: str) -> AutostartListing:
    return AutostartListing((), (AutostartSkipped(Source.LAUNCH_AGENT, str(path), detail),))


# --- items ---------------------------------------------------------------------------------


def test_a_user_agent_is_an_item(dirs: Dirs) -> None:
    path = plist(dirs[0], "com.example.sync.plist")

    (found,) = read(dirs).items

    assert found.source is Source.LAUNCH_AGENT
    assert found.scope is Scope.USER
    assert found.name == "com.example.sync"
    assert found.command == "/Applications/Sync.app/Contents/MacOS/sync --tray 'a b'"
    assert found.location == str(path)
    assert found.enabled is True
    assert found.notes == ("runs at load", FROM_FILE)
    assert found.digest == entry_digest(path.read_bytes())
    assert found.disableable is False


def test_system_agents_and_daemons_are_system_scope(dirs: Dirs) -> None:
    _, agents, daemons = dirs
    plist(agents, "a.plist", agent(Label="agent"))
    plist(daemons, "d.plist", agent(Label="daemon"))

    found = read(dirs).items

    assert [(i.name, i.scope, i.notes) for i in found] == [
        ("agent", Scope.SYSTEM, ("runs at load", FROM_FILE)),
        ("daemon", Scope.SYSTEM, ("daemon, started at boot", "runs at load", FROM_FILE)),
    ]


def test_the_directories() -> None:
    home, root = Path("/Users/me"), Path("/")

    assert launchd_dirs(home, root) == (
        Path("/Users/me/Library/LaunchAgents"),
        Path("/Library/LaunchAgents"),
        Path("/Library/LaunchDaemons"),
    )


def test_items_are_ordered_by_directory_then_file_name_ignoring_case(dirs: Dirs) -> None:
    user, agents, _ = dirs
    plist(agents, "a.plist", agent(Label="sys"))
    plist(user, "b.plist", agent(Label="b"))
    plist(user, "A.plist", agent(Label="a"))

    assert [i.name for i in read(dirs).items] == ["a", "b", "sys"]


def test_only_plist_files_are_read(dirs: Dirs) -> None:
    plist(dirs[0], "notes.txt", b"not a plist")
    plist(dirs[0], "backup.plist.bak", AGENT)

    assert read(dirs) == AutostartListing((), ())


def test_a_binary_property_list_is_read_too(dirs: Dirs) -> None:
    plist(dirs[0], "a.plist", binary=True)

    assert [i.name for i in read(dirs).items] == ["com.example.sync"]


@pytest.mark.parametrize(
    ("keys", "notes"),
    [
        ({"RunAtLoad": None, "KeepAlive": True}, ("kept alive",)),
        ({"RunAtLoad": None, "KeepAlive": {"Crashed": True}}, ("kept alive on conditions",)),
        ({"RunAtLoad": True, "KeepAlive": False}, ("runs at load",)),
        ({"RunAtLoad": False}, ("loaded at login, started on demand",)),
        ({"RunAtLoad": None, "StartInterval": 3600}, ("loaded at login, started on demand",)),
    ],
)
def test_run_at_load_and_keep_alive_become_notes(
    dirs: Dirs, keys: dict[str, object], notes: tuple[str, ...]
) -> None:
    plist(dirs[0], "a.plist", agent(**keys))

    (found,) = read(dirs).items

    assert found.notes == (*notes, FROM_FILE)


@pytest.mark.parametrize(("disabled", "enabled"), [(True, False), (False, True)])
def test_the_disabled_key_decides_the_state(dirs: Dirs, disabled: bool, enabled: bool) -> None:
    plist(dirs[0], "a.plist", agent(Disabled=disabled))

    (found,) = read(dirs).items

    assert found.enabled is enabled
    assert found.notes == ("runs at load", *(() if enabled else ("Disabled=true",)), FROM_FILE)


@pytest.mark.parametrize(
    ("keys", "command"),
    [
        ({"ProgramArguments": None, "Program": "/usr/local/bin/sync"}, "/usr/local/bin/sync"),
        ({"Program": "/opt/sync", "ProgramArguments": ["sync", "-d"]}, "/opt/sync -d"),
    ],
)
def test_program_is_the_executable_and_program_arguments_the_argv(
    dirs: Dirs, keys: dict[str, object], command: str
) -> None:
    plist(dirs[0], "a.plist", agent(**keys))

    assert [i.command for i in read(dirs).items] == [command]


# --- what is skipped ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        (agent(Label=None), "no Label"),
        (agent(Label=""), "no Label"),
        (agent(Label=7), "no Label"),
        (agent(ProgramArguments=None), "no Program or ProgramArguments"),
        (agent(ProgramArguments=[]), "empty command"),
        (agent(ProgramArguments=["/bin/x", 1]), "ProgramArguments is not a list of strings"),
        (agent(ProgramArguments="/bin/x"), "ProgramArguments is not a list of strings"),
        (agent(ProgramArguments=None, Program=""), "empty command"),
        (agent(ProgramArguments=None, Program=["/bin/x"]), "Program is not a string"),
        (agent(RunAtLoad="yes"), "RunAtLoad is not a boolean"),
        (agent(Disabled=1), "Disabled is not a boolean"),
        (agent(KeepAlive="always"), "KeepAlive is not a boolean or a dictionary"),
        (["not", "a", "dictionary"], "not a dictionary"),
        (b"not a property list", INVALID),
        (xml_plist("<key>A</key><string>x</key>"), INVALID),  # mismatched tag
        (xml_plist("<key>A</key><date>never</date>"), INVALID),
        (xml_plist("<key>A</key><integer>zz</integer>"), INVALID),
    ],
)
def test_an_agent_that_does_not_parse_is_skipped(dirs: Dirs, content: Content, detail: str) -> None:
    path = plist(dirs[0], "a.plist", content)

    assert read(dirs) == skip(path, detail)


def test_an_entity_declaration_is_refused(dirs: Dirs) -> None:
    raw = (
        b'<?xml version="1.0"?><!DOCTYPE plist [<!ENTITY a "aaaaaaaa">]>'
        b'<plist version="1.0"><dict><key>Label</key><string>&a;</string>'
        b"<key>Program</key><string>/bin/x</string></dict></plist>"
    )
    path = plist(dirs[0], "a.plist", raw)

    assert read(dirs) == skip(path, "not a valid property list")


def test_an_oversized_file_is_skipped_unread(dirs: Dirs) -> None:
    path = plist(dirs[0], "a.plist", agent(Padding="x" * MAX_ENTRY_BYTES))

    assert read(dirs) == skip(path, f"larger than {MAX_ENTRY_BYTES} bytes")


def test_something_that_is_not_a_regular_file_is_skipped(dirs: Dirs) -> None:
    dirs[0].mkdir(parents=True)
    make_fifo(dirs[0] / "pipe.plist")  # opening it would block: never opened

    assert read(dirs) == skip(dirs[0] / "pipe.plist", "not a regular file")


def test_a_directory_that_cannot_be_listed_is_skipped_and_the_others_are_read(dirs: Dirs) -> None:
    user, agents, daemons = dirs
    agents.parent.mkdir(parents=True)
    agents.write_bytes(b"")  # a file where a directory is listed: NotADirectoryError
    plist(user, "a.plist")
    plist(daemons, "d.plist", agent(Label="daemon"))

    listing = read(dirs)

    assert [i.name for i in listing.items] == ["com.example.sync", "daemon"]
    assert listing.skipped == (
        AutostartSkipped(Source.LAUNCH_AGENT, str(agents), f"cannot read: {cannot_list(agents)}"),
    )


def test_missing_directories_give_an_empty_listing(dirs: Dirs) -> None:
    assert read(dirs) == AutostartListing((), ())
