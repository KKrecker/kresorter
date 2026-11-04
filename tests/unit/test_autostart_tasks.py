"""Reading Windows scheduled tasks that start at boot or logon (step 4, commit 9; 0011).

Task definitions are XML files under ``%SystemRoot%\\System32\\Tasks``, one per task, in
folders. They are machine-wide, so nothing is read without ``include_machine`` (item 5). Only
tasks with a boot or logon trigger are autostart entries; tasks with other triggers only are
not listed. The command is the first action, as written. Parsing is strict and bounded: a DTD
is refused, so no entity is ever expanded. Real temporary trees; read-only.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from kresorter.autostart.entries import MAX_ENTRY_BYTES
from kresorter.autostart.models import (
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
    entry_digest,
)
from kresorter.autostart.tasks import read_tasks, tasks_dir
from support.host import cannot_list, make_fifo

NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
LOGON = "<LogonTrigger><Enabled>true</Enabled></LogonTrigger>"
BOOT = "<BootTrigger/>"
EXEC = r"<Exec><Command>C:\Sync\sync.exe</Command><Arguments>/tray</Arguments></Exec>"
W = str(Path("/w").resolve())  # absolute on every system: C:\w on Windows
OTHER = str(Path("/other").resolve())


def definition(
    triggers: str = LOGON, actions: str = EXEC, settings: str = "", encoding: str = "UTF-16"
) -> bytes:
    text = (
        f'<?xml version="1.0" encoding="{encoding}"?>\n'
        f'<Task version="1.2" xmlns="{NS}">'
        f"<Triggers>{triggers}</Triggers><Settings>{settings}</Settings>"
        f'<Actions Context="Author">{actions}</Actions></Task>'
    )
    return text.encode(encoding.lower())


def task(root: Path, name: str, raw: bytes | None = None) -> Path:
    path = root.joinpath(*name.split("\\"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(definition() if raw is None else raw)
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "Windows" / "System32" / "Tasks"


def read(root: Path) -> AutostartListing:
    return read_tasks(root, include_machine=True)


def skip(path: Path, detail: str) -> AutostartListing:
    return AutostartListing((), (AutostartSkipped(Source.SCHEDULED_TASK, str(path), detail),))


# --- items ---------------------------------------------------------------------------------


def test_a_logon_task_is_an_enabled_system_item(root: Path) -> None:
    path = task(root, "SyncAtLogon")

    (found,) = read(root).items

    assert found.source is Source.SCHEDULED_TASK
    assert found.scope is Scope.SYSTEM
    assert found.name == r"\SyncAtLogon"
    assert found.command == r"C:\Sync\sync.exe /tray"
    assert found.location == str(path)
    assert found.enabled is True
    assert found.notes == ("at logon",)
    assert found.digest == entry_digest(path.read_bytes())
    assert found.disableable is False


def test_nothing_is_read_without_consent(root: Path) -> None:
    task(root, "SyncAtLogon")

    assert read_tasks(root, include_machine=False) == AutostartListing((), ())


def test_the_name_is_the_task_path_and_folders_are_read(root: Path) -> None:
    task(root, r"Microsoft\Windows\Defrag\Boot", definition(BOOT))
    task(root, r"b\Task")
    task(root, "A")

    names = [i.name for i in read(root).items]

    assert names == [r"\A", r"\b\Task", r"\Microsoft\Windows\Defrag\Boot"]


@pytest.mark.parametrize(
    ("triggers", "notes"),
    [
        (BOOT, ("at boot",)),
        (LOGON + BOOT, ("at boot", "at logon")),
        ("<LogonTrigger><UserId>PC\\me</UserId></LogonTrigger>", ("at logon of PC\\me",)),
        (LOGON + "<TimeTrigger/>", ("at logon",)),
    ],
)
def test_boot_and_logon_triggers_become_notes(
    root: Path, triggers: str, notes: tuple[str, ...]
) -> None:
    task(root, "T", definition(triggers))

    (found,) = read(root).items

    assert found.notes == notes


@pytest.mark.parametrize(
    "triggers",
    [
        "",
        "<TimeTrigger/>",
        "<CalendarTrigger/><IdleTrigger/>",
        "<EventTrigger/><RegistrationTrigger/><SessionStateChangeTrigger/>",
    ],
)
def test_a_task_without_a_boot_or_logon_trigger_is_not_listed(root: Path, triggers: str) -> None:
    task(root, "T", definition(triggers))

    assert read(root) == AutostartListing((), ())


@pytest.mark.parametrize(
    ("triggers", "settings", "enabled", "notes"),
    [
        (LOGON, "<Enabled>false</Enabled>", False, ("at logon", "task disabled")),
        (LOGON, "<Enabled>0</Enabled>", False, ("at logon", "task disabled")),
        (LOGON, "<Enabled>1</Enabled>", True, ("at logon",)),
        (
            "<LogonTrigger><Enabled>false</Enabled></LogonTrigger>",
            "",
            False,
            ("at logon (trigger disabled)",),
        ),
        (
            "<LogonTrigger><Enabled>false</Enabled></LogonTrigger>" + BOOT,
            "",
            True,
            ("at boot", "at logon (trigger disabled)"),
        ),
    ],
)
def test_the_task_and_its_triggers_decide_the_state(
    root: Path, triggers: str, settings: str, enabled: bool, notes: tuple[str, ...]
) -> None:
    task(root, "T", definition(triggers, settings=settings))

    (found,) = read(root).items

    assert (found.enabled, found.notes) == (enabled, notes)


@pytest.mark.parametrize(
    ("actions", "command", "notes"),
    [
        ("<Exec><Command>%windir%\\app.exe</Command></Exec>", r"%windir%\app.exe", ()),
        (EXEC + EXEC, r"C:\Sync\sync.exe /tray", ("1 more action",)),
        (EXEC * 3, r"C:\Sync\sync.exe /tray", ("2 more actions",)),
        (
            "<ComHandler><ClassId>{0B8D4A53-1A6E-4C6C-9F2B-6E1B4A7C7D10}</ClassId></ComHandler>",
            "COM handler {0B8D4A53-1A6E-4C6C-9F2B-6E1B4A7C7D10}",
            ("COM handler, not resolved",),
        ),
    ],
)
def test_the_command_is_the_first_action_as_written(
    root: Path, actions: str, command: str, notes: tuple[str, ...]
) -> None:
    task(root, "T", definition(actions=actions))

    (found,) = read(root).items

    assert found.command == command
    assert found.notes == ("at logon", *notes)


def test_a_utf8_definition_is_read_too(root: Path) -> None:
    task(root, "T", definition(encoding="UTF-8"))

    assert [i.command for i in read(root).items] == [r"C:\Sync\sync.exe /tray"]


# --- what is skipped ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "detail"),
    [
        (definition(actions=""), "no actions"),
        (definition(actions="<Exec><Arguments>/x</Arguments></Exec>"), "empty command"),
        (definition(actions="<Exec><Command> </Command></Exec>"), "empty command"),
        (definition(actions="<ComHandler/>"), "COM handler without ClassId"),
        (definition(actions="<SendEmail/>"), "unsupported action SendEmail"),
        (definition(settings="<Enabled>yes</Enabled>"), "Enabled is not a boolean"),
        (
            definition("<LogonTrigger><Enabled>on</Enabled></LogonTrigger>"),
            "Enabled is not a boolean",
        ),
        (b'<?xml version="1.0"?><Task/>', "not a task definition"),
        (f'<Job xmlns="{NS}"/>'.encode(), "not a task definition"),
    ],
)
def test_a_task_that_does_not_parse_is_skipped(root: Path, raw: bytes, detail: str) -> None:
    path = task(root, "T", raw)

    assert read(root) == skip(path, detail)


def test_a_file_that_is_not_xml_is_skipped(root: Path) -> None:
    path = task(root, "T", b"\x00\x01 not xml")

    (skipped,) = read(root).skipped

    assert skipped.location == str(path)
    assert skipped.detail.startswith("not valid XML: ")


def test_a_dtd_is_refused_so_no_entity_is_expanded(root: Path) -> None:
    raw = (
        b'<?xml version="1.0"?><!DOCTYPE Task [<!ENTITY a "aaaaaaaa">]>'
        + f'<Task xmlns="{NS}"><Triggers>{LOGON}</Triggers>'.encode()
        + b"<Actions><Exec><Command>&a;</Command></Exec></Actions></Task>"
    )
    path = task(root, "T", raw)

    assert read(root) == skip(path, "a DTD is not allowed")


def test_an_oversized_definition_is_skipped_unread(root: Path) -> None:
    path = task(root, "T", definition(settings=" " * MAX_ENTRY_BYTES))

    assert read(root) == skip(path, f"larger than {MAX_ENTRY_BYTES} bytes")


def test_something_that_is_not_a_regular_file_is_skipped(root: Path) -> None:
    root.mkdir(parents=True)
    make_fifo(root / "pipe")  # opening it would block: never opened

    assert read(root) == skip(root / "pipe", "not a regular file")


def test_a_linked_folder_is_not_followed(root: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    task(elsewhere, "T")
    root.mkdir(parents=True)
    (root / "Linked").symlink_to(elsewhere, target_is_directory=True)

    assert read(root) == skip(root / "Linked", "not a regular file")


def test_a_tasks_folder_that_cannot_be_listed_is_one_skip(tmp_path: Path) -> None:
    not_a_folder = tmp_path / "Tasks"
    not_a_folder.write_bytes(b"")

    assert read(not_a_folder) == skip(not_a_folder, f"cannot read: {cannot_list(not_a_folder)}")


def test_a_sub_folder_that_cannot_be_listed_is_skipped_and_the_others_are_read(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task(root, r"Ok\T")
    locked = task(root, r"Locked\T").parent
    iterdir = Path.iterdir

    def denied(path: Path) -> Iterator[Path]:
        if path == locked:
            raise PermissionError(13, "Permission denied")
        return iterdir(path)

    monkeypatch.setattr(Path, "iterdir", denied)
    listing = read(root)

    assert [i.name for i in listing.items] == [r"\Ok\T"]
    assert listing.skipped == skip(locked, "cannot read: Permission denied").skipped


def test_a_missing_or_unknown_tasks_folder_gives_an_empty_listing(root: Path) -> None:
    assert read(root) == AutostartListing((), ())
    assert read_tasks(None, include_machine=True) == AutostartListing((), ())


# --- where the tasks are -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"SystemRoot": W, "windir": OTHER}, Path(W, "System32", "Tasks")),
        ({"windir": W}, Path(W, "System32", "Tasks")),
        ({"SystemRoot": "relative", "windir": W}, Path(W, "System32", "Tasks")),
        ({"SystemRoot": ""}, None),
        ({}, None),
    ],
)
def test_the_tasks_folder_comes_from_systemroot(env: dict[str, str], expected: Path | None) -> None:
    assert tasks_dir(env) == expected
