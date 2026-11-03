"""Disabling an XDG entry, journaled before it is made (step 4, commit 12a2; decision 0011).

The entry must still be exactly as listed (the whole item, read again). A user's own entry:
the copy with ``Hidden=true`` is staged in the autostart store, the original is linked into
the store (same inode) and the copy atomically replaces it, so the entry is never missing. A
system entry: the stub is created in the user directory with ``O_EXCL``; ``/etc`` is never
written. Every change is a ``pending`` row of ``autostart_changes`` before the disk is
touched; a failure rolls it back and nothing is ever deleted. Refusals change nothing and
journal nothing. Real files in tmp_path; OS failures are injected by patching ``os``.
"""

import functools
import itertools
import os
import sqlite3
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from fakes import deny_stat
from kresorter.autostart import changes
from kresorter.autostart.changes import AutostartStore, XdgChanges
from kresorter.autostart.entries import MAX_ENTRY_BYTES
from kresorter.autostart.journal import ChangeRefusal, ChangeResult, ChangeState
from kresorter.autostart.models import (
    AutostartItem,
    AutostartListing,
    Scope,
    Source,
    entry_digest,
)
from kresorter.autostart.xdg import read_xdg
from kresorter.autostart.xdg_changes import STUB, hidden_copy
from kresorter.storage.db import connect
from support.files import write_desktop

APP = b"[Desktop Entry]\nType=Application\nName=App\nExec=/usr/bin/app --tray\n"
COLUMNS = (
    "action, source, entry, location, digest, value_before, value_after, vault_path, state,"
    " error, finished_at_ns IS NOT NULL"
)

Row = tuple[object, ...]
Snapshot = list[tuple[str, bytes, int, int]]


@dataclass(frozen=True)
class Tree:
    root: Path
    user: Path
    system: Path
    store: AutostartStore
    conn: sqlite3.Connection
    changes: XdgChanges

    def listed(self) -> tuple[AutostartItem, ...]:
        return read_xdg(self.user, (self.system,)).items

    def item(self) -> AutostartItem:
        (item,) = self.listed()
        return item

    def rows(self) -> list[Row]:
        sql = f"SELECT {COLUMNS} FROM autostart_changes ORDER BY id"
        return self.conn.execute(sql).fetchall()

    def files(self) -> Snapshot:
        """Every file outside the data directory: name, bytes, inode, mtime."""
        return sorted(
            (str(p), p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns)
            for p in self.root.rglob("*")
            if p.is_file() and not p.is_relative_to(self.store.data_dir)
        )

    def stored(self) -> list[str]:
        """What the store holds; nothing if no change has made it yet (item 115)."""
        if not self.store.root.is_dir():
            return []
        return sorted(p.name for p in self.store.root.iterdir())


@pytest.fixture
def tree(tmp_path: Path) -> Iterator[Tree]:
    data = tmp_path / "data"
    data.mkdir()
    conn = connect(data / "journal.db")
    store = AutostartStore(data)
    user = tmp_path / "home" / ".config" / "autostart"
    system = tmp_path / "etc" / "xdg" / "autostart"
    yield Tree(tmp_path, user, system, store, conn, XdgChanges(conn, store, user, (system,)))
    conn.close()


def fail(*args: object, **kwargs: object) -> None:
    raise OSError(28, "No space left on device")


def interrupt(*args: object, **kwargs: object) -> None:
    raise KeyboardInterrupt


# --- the store ---------------------------------------------------------------------------------


def test_the_store_is_apart_from_the_quarantine_and_made_private_by_the_first_change(
    tree: Tree,
) -> None:
    assert tree.store.root == tree.store.data_dir / "autostart"
    assert tree.store.slot(7) == tree.store.root / "7"
    assert not tree.store.root.exists()  # not made by XdgChanges itself (item 115)
    write_desktop(tree.user, "app", APP)

    tree.changes.disable(tree.item())

    assert stat.S_IMODE(tree.store.root.stat().st_mode) == 0o700
    assert tree.stored() == ["1"]


def test_a_store_not_made_yet_is_on_the_device_of_the_directory_above_it(tmp_path: Path) -> None:
    store = AutostartStore(tmp_path / "data")

    assert store.device() == tmp_path.stat().st_dev
    assert not store.data_dir.exists()


def test_a_store_that_cannot_be_made_stops_the_change_before_it_is_journaled(tree: Tree) -> None:
    write_desktop(tree.user, "app", APP)
    data = tree.root / "other"
    data.mkdir()
    (data / "autostart").write_bytes(b"")  # a file where the store would be made
    store = AutostartStore(data)
    xdg = XdgChanges(tree.conn, store, tree.user, (tree.system,))
    files = tree.files()

    with pytest.raises(FileExistsError):
        xdg.disable(tree.item())

    assert (tree.files(), tree.rows()) == (files, [])


# --- a user's own entry ------------------------------------------------------------------------


def test_own_entry_is_replaced_by_its_hidden_copy(tree: Tree) -> None:
    path = write_desktop(tree.user, "app", APP)
    inode = path.stat().st_ino
    item = tree.item()

    result = tree.changes.disable(item)

    assert result == ChangeResult(1, ChangeState.DONE)
    assert path.read_bytes() == hidden_copy(APP)
    slot = tree.store.slot(1)
    assert slot.read_bytes() == APP
    assert slot.stat().st_ino == inode  # the original itself, not a copy of it
    assert tree.stored() == ["1"]
    (after,) = tree.listed()
    assert (after.location, after.enabled, after.command) == (str(path), False, item.command)


def test_own_entry_change_is_journaled(tree: Tree) -> None:
    path = write_desktop(tree.user, "app", APP)
    item = tree.item()

    tree.changes.disable(item)

    assert tree.rows() == [
        (
            "disable",
            "xdg_autostart",
            str(path),
            str(path),
            item.digest,
            APP,
            hidden_copy(APP),
            str(tree.store.slot(1)),
            "done",
            None,
            1,
        )
    ]


def test_journal_times_come_from_the_given_clock(tree: Tree) -> None:
    clock = functools.partial(next, itertools.count(1))
    xdg = XdgChanges(tree.conn, tree.store, tree.user, (tree.system,), now=clock)
    write_desktop(tree.user, "app", APP)

    xdg.disable(tree.item())
    xdg.enable(tree.item())

    sql = "SELECT action, created_at_ns, finished_at_ns FROM autostart_changes ORDER BY id"
    assert tree.conn.execute(sql).fetchall() == [("disable", 1, 2), ("enable", 3, 4)]  # item 121


def test_own_entry_over_a_system_entry_is_disabled_by_its_copy(tree: Tree) -> None:
    shadowed = write_desktop(tree.system, "app", APP)
    path = write_desktop(tree.user, "app", APP.replace(b"--tray", b"--quiet"))
    before = shadowed.read_bytes(), shadowed.stat().st_mtime_ns

    tree.changes.disable(tree.item())

    (after,) = tree.listed()
    assert (after.location, after.shadows, after.enabled) == (str(path), str(shadowed), False)
    assert after.command == "/usr/bin/app --quiet"
    assert (shadowed.read_bytes(), shadowed.stat().st_mtime_ns) == before


def test_the_journal_row_exists_before_the_entry_is_touched(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_desktop(tree.user, "app", APP)
    seen: list[list[Row]] = []
    link = os.link

    def watching(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        seen.append(tree.conn.execute("SELECT state FROM autostart_changes").fetchall())
        link(source, target)

    monkeypatch.setattr(os, "link", watching)

    tree.changes.disable(tree.item())

    assert seen == [[("pending",)]]


# --- a system entry ----------------------------------------------------------------------------


def test_system_entry_is_hidden_by_a_user_stub(tree: Tree) -> None:
    shadowed = write_desktop(tree.system, "app", APP)
    before = shadowed.read_bytes(), shadowed.stat().st_mtime_ns
    item = tree.item()

    result = tree.changes.disable(item)

    assert result == ChangeResult(1, ChangeState.DONE)
    stub = tree.user / "app.desktop"
    assert stub.read_bytes() == STUB
    assert (shadowed.read_bytes(), shadowed.stat().st_mtime_ns) == before
    (after,) = tree.listed()
    assert (after.location, after.shadows, after.enabled) == (str(stub), str(shadowed), False)
    assert tree.rows() == [
        (
            "disable",
            "xdg_autostart",
            str(shadowed),
            str(stub),
            item.digest,
            None,
            STUB,
            None,
            "done",
            None,
            1,
        )
    ]
    assert tree.stored() == []


def test_a_missing_user_directory_is_created_private(tree: Tree) -> None:
    write_desktop(tree.system, "app", APP)
    assert not tree.user.parent.exists()

    tree.changes.disable(tree.item())

    assert stat.S_IMODE(tree.user.stat().st_mode) == 0o700
    assert (tree.user / "app.desktop").read_bytes() == STUB


def test_an_existing_user_directory_keeps_its_mode(tree: Tree) -> None:
    write_desktop(tree.system, "app", APP)
    tree.user.mkdir(parents=True)
    tree.user.chmod(0o755)

    tree.changes.disable(tree.item())

    assert stat.S_IMODE(tree.user.stat().st_mode) == 0o755
    assert (tree.user / "app.desktop").read_bytes() == STUB


# --- refusals: nothing changes, nothing is journaled -------------------------------------------


def assert_refused(
    tree: Tree, result: ChangeResult, refusal: ChangeRefusal, files: Snapshot
) -> None:
    assert (result.change_id, result.state, result.refusal) == (None, None, refusal)
    assert result.detail
    assert tree.files() == files
    assert tree.rows() == []
    assert not tree.store.root.exists()  # nothing in the store: not even the store (item 115)


def test_a_read_only_source_is_refused(tree: Tree) -> None:
    unit = AutostartItem(
        source=Source.SYSTEMD_USER,
        scope=Scope.USER,
        name="sync.service",
        command="/usr/bin/sync",
        location=str(tree.root / "sync.service"),
        enabled=True,
        digest=entry_digest(b"unit"),
    )

    result = tree.changes.disable(unit)

    assert_refused(tree, result, ChangeRefusal.READ_ONLY, [])


def test_an_entry_edited_since_it_was_listed_is_refused(tree: Tree) -> None:
    path = write_desktop(tree.user, "app", APP)
    item = tree.item()
    path.write_bytes(APP.replace(b"--tray", b"--evil"))
    files = tree.files()

    result = tree.changes.disable(item)

    assert_refused(tree, result, ChangeRefusal.CHANGED, files)


def test_an_entry_gone_since_it_was_listed_is_refused(tree: Tree) -> None:
    path = write_desktop(tree.user, "app", APP)
    item = tree.item()
    path.rename(tree.root / "elsewhere.desktop")
    files = tree.files()

    result = tree.changes.disable(item)

    assert_refused(tree, result, ChangeRefusal.CHANGED, files)


@pytest.mark.parametrize("edit", ["rewrite", "move"])
def test_an_entry_changed_right_after_the_check_is_refused(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, edit: str
) -> None:
    # The listing is read again first; the bytes the copy is made of are compared once more.
    path = write_desktop(tree.user, "app", APP)
    item = tree.item()
    stale = AutostartListing((item,), ())

    def read_before_the_edit(user: Path, system: tuple[Path, ...]) -> AutostartListing:
        if edit == "rewrite":
            path.write_bytes(APP.replace(b"--tray", b"--evil"))
        else:
            path.rename(tree.root / "elsewhere.desktop")
        return stale

    monkeypatch.setattr(changes, "read_xdg", read_before_the_edit)

    result = tree.changes.disable(item)

    assert (result.change_id, result.state, result.refusal) == (None, None, ChangeRefusal.CHANGED)
    assert (tree.rows(), tree.stored()) == ([], [])


def test_a_system_entry_shadowed_since_it_was_listed_is_refused(tree: Tree) -> None:
    write_desktop(tree.system, "app", APP)
    item = tree.item()
    write_desktop(tree.user, "app", APP)  # a user entry now replaces the listed one
    files = tree.files()

    result = tree.changes.disable(item)

    assert_refused(tree, result, ChangeRefusal.CHANGED, files)


@pytest.mark.parametrize(
    "raw",
    [
        APP + b"X-GNOME-Autostart-enabled=false\n",
        APP.replace(b"[Desktop Entry]\n", b"[Desktop Entry]\nHidden=true\n"),
    ],
    ids=["gnome-disabled", "hidden"],
)
def test_an_own_entry_already_disabled_is_refused(tree: Tree, raw: bytes) -> None:
    write_desktop(tree.user, "app", raw)
    files = tree.files()

    result = tree.changes.disable(tree.item())

    assert_refused(tree, result, ChangeRefusal.ALREADY, files)


def test_a_system_entry_already_hidden_is_refused(tree: Tree) -> None:
    write_desktop(tree.system, "app", APP)
    write_desktop(tree.user, "app", STUB)
    files = tree.files()

    result = tree.changes.disable(tree.item())

    assert_refused(tree, result, ChangeRefusal.ALREADY, files)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO autostart_changes (action, source, entry, location, digest, value_after,"
        " state, created_at_ns) VALUES ('disable', 'xdg_autostart', '/e', '/l',"
        " '0123456789abcdef0123456789abcdef', x'00', 'pending', 1)",
        "INSERT INTO operations (kind, state, created_at_ns) VALUES ('quarantine', 'pending', 1)",
    ],
    ids=["autostart-change", "quarantine-operation"],
)
def test_unfinished_work_in_the_journal_is_refused(tree: Tree, sql: str) -> None:
    write_desktop(tree.user, "app", APP)
    tree.conn.execute(sql)
    files = tree.files()
    rows = tree.rows()

    result = tree.changes.disable(tree.item())

    assert (result.change_id, result.state, result.refusal) == (None, None, ChangeRefusal.PENDING)
    assert "recover" in result.detail
    assert (tree.files(), tree.rows(), tree.stored()) == (files, rows, [])


def other_device() -> int:
    return -1


@pytest.mark.parametrize("scope", [Scope.USER, Scope.SYSTEM])
def test_a_store_on_another_device_is_refused(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, scope: Scope
) -> None:
    write_desktop(tree.user if scope is Scope.USER else tree.system, "app", APP)
    files = tree.files()
    monkeypatch.setattr(tree.store, "device", other_device)

    result = tree.changes.disable(tree.item())

    assert_refused(tree, result, ChangeRefusal.OTHER_DEVICE, files)


def test_a_user_directory_the_system_denies_is_not_taken_for_a_missing_one(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_desktop(tree.system, "app", APP)
    tree.user.mkdir(parents=True)
    item = tree.item()
    files = tree.files()
    deny_stat(monkeypatch, tree.user)  # its device is unknown; the one above it is not its own

    with pytest.raises(PermissionError, match="Permission denied"):
        tree.changes.disable(item)

    monkeypatch.undo()
    assert (tree.files(), tree.rows(), tree.stored()) == (files, [], [])


def test_an_own_entry_whose_copy_would_be_too_large_is_refused(tree: Tree) -> None:
    raw = APP + b"#" * (MAX_ENTRY_BYTES - len(APP) - 1) + b"\n"
    write_desktop(tree.user, "app", raw)
    files = tree.files()

    result = tree.changes.disable(tree.item())

    assert_refused(tree, result, ChangeRefusal.TOO_LARGE, files)


# --- failures: rolled back, nothing deleted ----------------------------------------------------


def assert_rolled_back(tree: Tree, result: ChangeResult, files: Snapshot) -> None:
    assert (result.change_id, result.state, result.refusal) == (1, ChangeState.ROLLED_BACK, None)
    assert "No space left on device" in result.detail
    assert tree.files() == files
    ((state, error),) = tree.conn.execute("SELECT state, error FROM autostart_changes")
    assert (state, error) == ("rolled_back", result.detail)


@pytest.mark.parametrize("step", ["link", "replace", "fsync"])
def test_own_entry_stays_as_it_was_when_a_step_fails(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    write_desktop(tree.user, "app", APP)
    files = tree.files()
    item = tree.item()
    monkeypatch.setattr(os, step, fail)

    result = tree.changes.disable(item)

    assert_rolled_back(tree, result, files)
    assert tree.listed() == (item,)


def test_stub_that_could_not_be_created_leaves_nothing(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_desktop(tree.system, "app", APP)
    files = tree.files()
    item = tree.item()
    monkeypatch.setattr(os, "open", fail)

    result = tree.changes.disable(item)

    assert_rolled_back(tree, result, files)
    assert tree.stored() == []
    assert tree.listed() == (item,)


def test_stub_written_but_not_synced_goes_to_the_store(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_desktop(tree.system, "app", APP)
    tree.user.mkdir(parents=True)
    files = tree.files()
    item = tree.item()
    monkeypatch.setattr(os, "fsync", fail)

    result = tree.changes.disable(item)

    assert_rolled_back(tree, result, files)
    assert tree.stored() == ["1"]
    assert tree.store.slot(1).read_bytes() == STUB
    (vault_path,) = tree.conn.execute("SELECT vault_path FROM autostart_changes").fetchone()
    assert vault_path == str(tree.store.slot(1))
    assert tree.listed() == (item,)


def test_a_file_that_took_the_place_of_the_stub_is_kept_and_the_change_rolled_back(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_desktop(tree.system, "app", APP)
    item = tree.item()
    stub = tree.user / "app.desktop"
    mine = b"[Desktop Entry]\nType=Application\nName=Mine\nExec=/usr/bin/mine\n"
    create = os.open

    def taken_first(path: Path, flags: int, mode: int = 0o777) -> int:
        if Path(path) == stub:
            stub.write_bytes(mine)  # the user's own file, right after the check
        return create(path, flags, mode)

    monkeypatch.setattr(os, "open", taken_first)
    result = tree.changes.disable(item)
    monkeypatch.undo()

    assert (result.change_id, result.state, result.refusal) == (1, ChangeState.ROLLED_BACK, None)
    assert "File exists" in result.detail
    ((state, error),) = tree.conn.execute("SELECT state, error FROM autostart_changes")
    assert (state, error) == ("rolled_back", result.detail)  # nothing of ours is there (item 117)
    assert stub.read_bytes() == mine  # never overwritten (item 68)
    assert tree.stored() == []


@pytest.mark.parametrize("scope", [Scope.USER, Scope.SYSTEM])
def test_an_interrupt_is_rolled_back_and_raised(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, scope: Scope
) -> None:
    write_desktop(tree.user if scope is Scope.USER else tree.system, "app", APP)
    item = tree.item()
    monkeypatch.setattr(os, "fsync", interrupt)

    with pytest.raises(KeyboardInterrupt):
        tree.changes.disable(item)

    ((state, error),) = tree.conn.execute("SELECT state, error FROM autostart_changes")
    assert (state, error) == ("rolled_back", "KeyboardInterrupt")
    assert tree.listed() == (item,)


# --- enable: an own entry disabled here gets its original back ----------------------------------


def disabled(tree: Tree, scope: Scope = Scope.USER) -> AutostartItem:
    """An entry disabled by kresorter (change 1), as listed now."""
    write_desktop(tree.user if scope is Scope.USER else tree.system, "app", APP)
    assert tree.changes.disable(tree.item()) == ChangeResult(1, ChangeState.DONE)
    return tree.item()


def test_own_entry_disabled_here_gets_its_original_back(tree: Tree) -> None:
    path = write_desktop(tree.user, "app", APP)
    inode = path.stat().st_ino
    original = tree.item()
    tree.changes.disable(original)

    result = tree.changes.enable(tree.item())

    assert result == ChangeResult(2, ChangeState.DONE)
    assert path.read_bytes() == APP
    assert path.stat().st_ino == inode  # the original itself, moved back from the store
    assert tree.store.slot(2).read_bytes() == hidden_copy(APP)  # the copy is kept, not deleted
    assert tree.stored() == ["2"]
    assert tree.listed() == (original,)


def test_own_entry_enable_is_journaled(tree: Tree) -> None:
    item = disabled(tree)

    tree.changes.enable(item)

    path = str(tree.user / "app.desktop")
    copy = hidden_copy(APP)
    assert tree.rows()[1:] == [
        (
            "enable",
            "xdg_autostart",
            path,
            path,
            entry_digest(copy),
            copy,
            APP,
            str(tree.store.slot(2)),
            "done",
            None,
            1,
        )
    ]


def test_disable_and_enable_can_be_repeated(tree: Tree) -> None:
    path = write_desktop(tree.user, "app", APP)
    inode = path.stat().st_ino

    for _ in range(2):
        assert tree.changes.disable(tree.item()).state is ChangeState.DONE
        assert tree.changes.enable(tree.item()).state is ChangeState.DONE

    assert (path.read_bytes(), path.stat().st_ino) == (APP, inode)
    assert [(row[0], row[8]) for row in tree.rows()] == [
        ("disable", "done"),
        ("enable", "done"),
        ("disable", "done"),
        ("enable", "done"),
    ]
    assert tree.stored() == ["2", "4"]


def test_the_enable_row_exists_before_the_entry_is_touched(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = disabled(tree)
    seen: list[list[Row]] = []
    link = os.link

    def watching(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        seen.append(tree.conn.execute("SELECT action, state FROM autostart_changes").fetchall())
        link(source, target)

    monkeypatch.setattr(os, "link", watching)

    tree.changes.enable(item)

    assert seen == [[("disable", "done"), ("enable", "pending")]]


# --- enable: a stub over a system entry is moved to the store ----------------------------------


def test_stub_made_here_is_moved_to_the_store(tree: Tree) -> None:
    shadowed = write_desktop(tree.system, "app", APP)
    before = shadowed.read_bytes(), shadowed.stat().st_mtime_ns
    system_item = tree.item()
    tree.changes.disable(system_item)
    stub = tree.user / "app.desktop"

    result = tree.changes.enable(tree.item())

    assert result == ChangeResult(2, ChangeState.DONE)
    assert not stub.exists()
    assert tree.store.slot(2).read_bytes() == STUB
    assert (shadowed.read_bytes(), shadowed.stat().st_mtime_ns) == before
    assert tree.listed() == (system_item,)
    assert tree.rows()[1:] == [
        (
            "enable",
            "xdg_autostart",
            str(stub),
            str(stub),
            entry_digest(STUB),
            STUB,
            None,
            str(tree.store.slot(2)),
            "done",
            None,
            1,
        )
    ]


def test_a_users_own_stub_is_moved_too(tree: Tree) -> None:
    # Moving it edits nothing (item 74); a stub may carry other keys.
    write_desktop(tree.system, "app", APP)
    raw = b"[Desktop Entry]\nName=App\nHidden=true\n"
    write_desktop(tree.user, "app", raw)

    result = tree.changes.enable(tree.item())

    assert result == ChangeResult(1, ChangeState.DONE)
    assert tree.store.slot(1).read_bytes() == raw
    (item,) = tree.listed()
    assert (item.scope, item.enabled) == (Scope.SYSTEM, True)


# --- enable: refusals change nothing -----------------------------------------------------------


State = tuple[Snapshot, list[Row], list[str]]


def state(tree: Tree) -> State:
    return tree.files(), tree.rows(), tree.stored()


def assert_unchanged(
    tree: Tree, result: ChangeResult, refusal: ChangeRefusal, before: State
) -> None:
    assert (result.change_id, result.state, result.refusal) == (None, None, refusal)
    assert result.detail
    assert state(tree) == before


def test_enabling_a_read_only_source_is_refused(tree: Tree) -> None:
    unit = AutostartItem(
        source=Source.SYSTEMD_USER,
        scope=Scope.USER,
        name="sync.service",
        command="/usr/bin/sync",
        location=str(tree.root / "sync.service"),
        enabled=False,
        digest=entry_digest(b"unit"),
    )
    before = state(tree)

    assert_unchanged(tree, tree.changes.enable(unit), ChangeRefusal.READ_ONLY, before)


@pytest.mark.parametrize("scope", [Scope.USER, Scope.SYSTEM])
def test_enabling_an_enabled_entry_is_refused(tree: Tree, scope: Scope) -> None:
    write_desktop(tree.user if scope is Scope.USER else tree.system, "app", APP)
    before = state(tree)

    assert_unchanged(tree, tree.changes.enable(tree.item()), ChangeRefusal.ALREADY, before)


@pytest.mark.parametrize(
    ("scope", "raw"),
    [
        pytest.param(
            Scope.USER,
            APP.replace(b"[Desktop Entry]\n", b"[Desktop Entry]\nHidden=true\n"),
            id="own-hidden",
        ),
        pytest.param(Scope.USER, APP + b"X-GNOME-Autostart-enabled=false\n", id="own-gnome"),
        pytest.param(
            Scope.SYSTEM,
            APP.replace(b"[Desktop Entry]\n", b"[Desktop Entry]\nHidden=true\n"),
            id="system-hidden",
        ),
        pytest.param(Scope.SYSTEM, APP + b"X-GNOME-Autostart-enabled=false\n", id="system-gnome"),
    ],
)
def test_an_entry_disabled_elsewhere_is_refused(tree: Tree, scope: Scope, raw: bytes) -> None:
    # Enabling it would edit its content (item 74).
    write_desktop(tree.user if scope is Scope.USER else tree.system, "app", raw)
    before = state(tree)

    assert_unchanged(tree, tree.changes.enable(tree.item()), ChangeRefusal.FOREIGN, before)


def test_a_disabled_copy_edited_by_the_user_is_refused(tree: Tree) -> None:
    disabled(tree)
    path = tree.user / "app.desktop"
    path.write_bytes(hidden_copy(APP).replace(b"Name=App", b"Name=Renamed"))
    before = state(tree)

    assert_unchanged(tree, tree.changes.enable(tree.item()), ChangeRefusal.FOREIGN, before)


def test_an_entry_disabled_again_by_hand_is_refused(tree: Tree) -> None:
    # The last change journaled for this file is an enable: this copy was not written here.
    item = disabled(tree)
    path = tree.user / "app.desktop"
    tree.changes.enable(item)
    path.write_bytes(hidden_copy(APP))
    before = state(tree)

    assert_unchanged(tree, tree.changes.enable(tree.item()), ChangeRefusal.FOREIGN, before)


def test_enabling_an_entry_edited_since_it_was_listed_is_refused(tree: Tree) -> None:
    item = disabled(tree)
    (tree.user / "app.desktop").write_bytes(STUB)
    before = state(tree)

    assert_unchanged(tree, tree.changes.enable(item), ChangeRefusal.CHANGED, before)


@pytest.mark.parametrize("scope", [Scope.USER, Scope.SYSTEM])
def test_enabling_an_entry_changed_right_after_the_check_is_refused(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, scope: Scope
) -> None:
    item = disabled(tree, scope)
    path = tree.user / "app.desktop"
    stale = AutostartListing((item,), ())

    def read_before_the_edit(user: Path, system: tuple[Path, ...]) -> AutostartListing:
        path.write_bytes(path.read_bytes() + b"# edited\n")
        return stale

    monkeypatch.setattr(changes, "read_xdg", read_before_the_edit)

    result = tree.changes.enable(item)

    assert (result.change_id, result.state, result.refusal) == (None, None, ChangeRefusal.CHANGED)
    assert len(tree.rows()) == 1


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_an_original_missing_or_changed_in_the_store_is_refused(tree: Tree, damage: str) -> None:
    item = disabled(tree)
    slot = tree.store.slot(1)
    if damage == "missing":
        slot.rename(tree.store.root / "elsewhere")
    else:
        slot.write_bytes(b"[Desktop Entry]\nType=Application\nExec=/tmp/evil\n")
    before = state(tree)

    result = tree.changes.enable(item)

    assert_unchanged(tree, result, ChangeRefusal.ORIGINAL_CHANGED, before)


def test_enabling_with_unfinished_work_in_the_journal_is_refused(tree: Tree) -> None:
    item = disabled(tree)
    tree.conn.execute(
        "INSERT INTO operations (kind, state, created_at_ns) VALUES ('quarantine', 'pending', 1)"
    )
    before = state(tree)

    assert_unchanged(tree, tree.changes.enable(item), ChangeRefusal.PENDING, before)


@pytest.mark.parametrize("scope", [Scope.USER, Scope.SYSTEM])
def test_enabling_with_the_store_on_another_device_is_refused(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, scope: Scope
) -> None:
    item = disabled(tree, scope)
    monkeypatch.setattr(tree.store, "device", other_device)
    before = state(tree)

    assert_unchanged(tree, tree.changes.enable(item), ChangeRefusal.OTHER_DEVICE, before)


# --- enable: failures are rolled back, nothing deleted -----------------------------------------


def assert_enable_rolled_back(tree: Tree, result: ChangeResult, item: AutostartItem) -> None:
    assert (result.change_id, result.state, result.refusal) == (2, ChangeState.ROLLED_BACK, None)
    assert "No space left on device" in result.detail
    assert tree.listed() == (item,)
    rows = tree.conn.execute("SELECT state, error FROM autostart_changes ORDER BY id").fetchall()
    assert rows == [("done", None), ("rolled_back", result.detail)]


@pytest.mark.parametrize("step", ["link", "replace"])
def test_own_entry_stays_disabled_when_a_step_fails(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    item = disabled(tree)
    monkeypatch.setattr(os, step, fail)

    result = tree.changes.enable(item)

    assert_enable_rolled_back(tree, result, item)
    assert tree.store.slot(1).read_bytes() == APP  # the original is still in the store


def test_stub_stays_when_it_cannot_be_moved(tree: Tree, monkeypatch: pytest.MonkeyPatch) -> None:
    item = disabled(tree, Scope.SYSTEM)
    monkeypatch.setattr(os, "rename", fail)

    result = tree.changes.enable(item)

    assert_enable_rolled_back(tree, result, item)
    assert (tree.user / "app.desktop").read_bytes() == STUB


def test_an_interrupted_enable_is_rolled_back_and_raised(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = disabled(tree)
    monkeypatch.setattr(os, "replace", interrupt)

    with pytest.raises(KeyboardInterrupt):
        tree.changes.enable(item)

    rows = tree.conn.execute("SELECT state, error FROM autostart_changes ORDER BY id").fetchall()
    assert rows == [("done", None), ("rolled_back", "KeyboardInterrupt")]
    assert tree.listed() == (item,)
