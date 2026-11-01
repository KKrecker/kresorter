"""Reconciling unfinished XDG changes with the disk (step 4, commit 12b3; decision 0011).

A ``pending`` row is a change interrupted between the journal and its end. ``recover()`` closes
it by what is on disk: ``done`` if the entry is as after the change and the store holds what
the change kept there, ``rolled_back`` if the entry is as before, ``failed`` otherwise. Nothing
is redone or undone, and a staged ``<id>.new`` is never put in place: it stays in the store,
which is never purged. A ``failed`` row, the last change at its location, is reconciled the
same way; a partial stub left by a double fault is moved to the store, never deleted. An entry
that exists but cannot be read leaves the row as it is and raises. Real files in tmp_path; a
crash is injected by raising from ``os`` and from ``finish_change``.
"""

import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from fakes import deny_stat
from safeclean.autostart import changes
from safeclean.autostart.changes import AutostartStore, ChangeRecovery, ChangeState, XdgChanges
from safeclean.autostart.entries import BrokenEntryError
from safeclean.autostart.models import AutostartItem, Source
from safeclean.autostart.xdg import read_xdg
from safeclean.autostart.xdg_changes import STUB, hidden_copy
from safeclean.storage.db import connect
from safeclean.storage.transactions import transaction

APP = b"[Desktop Entry]\nType=Application\nName=App\nExec=/usr/bin/app --tray\n"
COPY = hidden_copy(APP)
MINE = b"[Desktop Entry]\nType=Application\nName=Mine\nExec=/usr/bin/mine\n"
AS_BEFORE = "the entry is as it was before the change"
NEITHER = "the entry is neither as before nor as after the change"
NOT_KEPT = "the entry is as after the change, but the store does not hold what it kept"
PARTIAL = "a partial stub was moved to the store"


class Crash(BaseException):
    """The process dying at this point: nothing after it runs, not even the journal update."""


def crash(*args: object, **kwargs: object) -> None:
    raise Crash


def fail(*args: object, **kwargs: object) -> None:
    raise OSError(28, "No space left on device")


@dataclass(frozen=True)
class Tree:
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

    def states(self) -> list[tuple[object, ...]]:
        sql = "SELECT state, error, finished_at_ns IS NOT NULL FROM autostart_changes ORDER BY id"
        return self.conn.execute(sql).fetchall()

    def vault_path(self, change_id: int) -> object:
        sql = "SELECT vault_path FROM autostart_changes WHERE id = ?"
        return self.conn.execute(sql, (change_id,)).fetchone()[0]

    def stored(self) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in sorted(self.store.root.iterdir())}


@pytest.fixture
def tree(tmp_path: Path) -> Iterator[Tree]:
    data = tmp_path / "data"
    data.mkdir()
    conn = connect(data / "journal.db")
    store = AutostartStore(data)
    user = tmp_path / "home" / ".config" / "autostart"
    system = tmp_path / "etc" / "xdg" / "autostart"
    yield Tree(user, system, store, conn, XdgChanges(conn, store, user, (system,)))
    conn.close()


def write(directory: Path, name: str, raw: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.desktop"
    path.write_bytes(raw)
    return path


def interrupted(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, action: str, step: str | None
) -> AutostartItem:
    """Run ``action`` on the only entry, dying at ``os.<step>`` (or right before the end)."""
    item = tree.item()
    if step is not None:
        monkeypatch.setattr(os, step, crash)
    monkeypatch.setattr(changes, "finish_change", crash)
    with pytest.raises(Crash):
        getattr(tree.changes, action)(item)
    monkeypatch.undo()
    return item


# --- pending changes -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("system", "step", "state", "stored"),
    [
        (False, "open", "rolled_back", {}),
        (False, "link", "rolled_back", {"1.new": COPY}),
        (False, "replace", "rolled_back", {"1": APP, "1.new": COPY}),
        (False, None, "done", {"1": APP}),
        (True, "open", "rolled_back", {}),
        (True, "fsync", "rolled_back", {"1": STUB}),
        (True, None, "done", {}),
    ],
    ids=[
        "own-before-staging",
        "own-staged",
        "own-linked",
        "own-replaced",
        "stub-not-created",
        "stub-not-synced",
        "stub-created",
    ],
)
def test_an_interrupted_disable_is_closed_by_the_disk(
    tree: Tree,
    monkeypatch: pytest.MonkeyPatch,
    system: bool,
    step: str | None,
    state: str,
    stored: dict[str, bytes],
) -> None:
    write(tree.system if system else tree.user, "app", APP)
    item = interrupted(tree, monkeypatch, "disable", step)
    assert tree.states() == [("pending", None, 0)]

    report = tree.changes.recover()

    assert report == ChangeRecovery(**{state: (1,)})
    assert tree.states() == [(state, None if state == "done" else AS_BEFORE, 1)]
    assert tree.stored() == stored  # a staged copy stays in the store, never put in place
    (now,) = tree.listed()
    assert now.enabled is (state != "done")
    assert now.command == item.command


@pytest.mark.parametrize(
    ("system", "step", "state", "stored"),
    [
        (False, "link", "rolled_back", ["1"]),
        (False, "replace", "rolled_back", ["1", "2"]),
        (False, None, "done", ["2"]),
        (True, "rename", "rolled_back", []),
        (True, None, "done", ["2"]),
    ],
    ids=["own-not-linked", "own-linked", "own-replaced", "stub-not-moved", "stub-moved"],
)
def test_an_interrupted_enable_is_closed_by_the_disk(
    tree: Tree,
    monkeypatch: pytest.MonkeyPatch,
    system: bool,
    step: str | None,
    state: str,
    stored: list[str],
) -> None:
    write(tree.system if system else tree.user, "app", APP)
    tree.changes.disable(tree.item())
    interrupted(tree, monkeypatch, "enable", step)

    report = tree.changes.recover()

    assert report == ChangeRecovery(**{state: (2,)})
    assert tree.states()[1] == (state, None if state == "done" else AS_BEFORE, 1)
    assert sorted(tree.stored()) == stored
    assert tree.item().enabled is (state == "done")


def test_done_needs_the_store_to_hold_what_the_change_kept(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tree.user, "app", APP)
    interrupted(tree, monkeypatch, "disable", None)
    tree.store.slot(1).write_bytes(MINE)  # the original kept in the store is not there anymore

    report = tree.changes.recover()

    assert report == ChangeRecovery(failed=(1,))
    assert tree.states() == [("failed", NOT_KEPT, 1)]


def test_an_entry_changed_since_the_interruption_is_failed(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tree.user, "app", APP)
    interrupted(tree, monkeypatch, "disable", "replace")
    path.write_bytes(MINE)

    report = tree.changes.recover()

    assert report == ChangeRecovery(failed=(1,))
    assert tree.states() == [("failed", NEITHER, 1)]
    assert path.read_bytes() == MINE  # recover() never writes over what it does not know


def test_an_unreadable_entry_leaves_the_row_pending_and_raises(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = write(tree.user, "app", APP)
    interrupted(tree, monkeypatch, "disable", "replace")
    path.rename(tmp_path / "elsewhere")
    path.mkdir()  # exists, but is not an entry that can be read

    with pytest.raises(BrokenEntryError, match="not a regular file"):
        tree.changes.recover()

    assert tree.states() == [("pending", None, 0)]


@pytest.mark.parametrize(("system", "there"), [(False, COPY), (True, STUB)], ids=["own", "stub"])
def test_an_entry_the_system_denies_is_not_taken_for_a_missing_one(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, system: bool, there: bytes
) -> None:
    write(tree.system if system else tree.user, "app", APP)
    interrupted(tree, monkeypatch, "disable", None)  # written, but not journaled as done
    entry = tree.user / "app.desktop"  # the copy, or the stub, is there
    deny_stat(monkeypatch, entry)

    with pytest.raises(BrokenEntryError, match="cannot read: Permission denied"):
        tree.changes.recover()

    monkeypatch.undo()
    assert tree.states() == [("pending", None, 0)]
    assert entry.read_bytes() == there


# --- failed changes ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "left", "state", "error", "stored"),
    [
        ("write", b"", "rolled_back", PARTIAL, {"1": b""}),
        ("fsync", STUB, "done", None, {}),
    ],
    ids=["stub-not-written", "stub-written-not-synced"],
)
def test_a_stub_left_by_a_double_fault_is_reconciled(
    tree: Tree,
    monkeypatch: pytest.MonkeyPatch,
    step: str,
    left: bytes,
    state: str,
    error: str | None,
    stored: dict[str, bytes],
) -> None:
    write(tree.system, "app", APP)
    item = tree.item()
    monkeypatch.setattr(os, step, fail)
    monkeypatch.setattr(os, "rename", fail)  # the partial stub cannot go to the store either
    result = tree.changes.disable(item)
    monkeypatch.undo()
    stub = tree.user / "app.desktop"
    assert (result.state, stub.read_bytes()) == (ChangeState.FAILED, left)

    report = tree.changes.recover()

    assert report == ChangeRecovery(**{state: (1,)})
    assert tree.states() == [(state, error, 1)]
    assert tree.stored() == stored
    if state == "rolled_back":
        assert tree.vault_path(1) == str(tree.store.slot(1))
        assert tree.listed() == (item,)
    else:
        assert tree.item().enabled is False


def double_fault(tree: Tree, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Change 1 failed, leaving an empty stub; returns the stub."""
    write(tree.system, "app", APP)
    monkeypatch.setattr(os, "write", fail)
    monkeypatch.setattr(os, "rename", fail)
    tree.changes.disable(tree.item())
    monkeypatch.undo()
    return tree.user / "app.desktop"


def test_a_failed_change_that_is_still_neither_stays_failed(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = double_fault(tree, monkeypatch)
    stub.write_bytes(MINE)
    before = tree.states()

    report = tree.changes.recover()

    assert report == ChangeRecovery()
    assert tree.states() == before  # its error is kept
    assert stub.read_bytes() == MINE


def test_a_failed_change_is_reconciled_only_if_it_is_the_last_one_there(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = double_fault(tree, monkeypatch)
    source, digest = Source.XDG_AUTOSTART, "0" * 32
    later = changes.Change("enable", source, str(stub), str(stub), digest, b"", None)
    with transaction(tree.conn):
        changes.insert_change(tree.conn, later)
    changes.finish_change(tree.conn, 2, ChangeState.DONE, None)
    before = tree.states()

    report = tree.changes.recover()

    assert report == ChangeRecovery()
    assert tree.states() == before
    assert stub.read_bytes() == b""


# --- what recover() leaves alone ------------------------------------------------------------------


def test_registry_rows_are_left_alone(tree: Tree) -> None:
    location = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run\App"
    change = changes.Change("disable", Source.RUN_KEY, "Run", location, "0" * 32, None, b"\x03")
    with transaction(tree.conn):
        changes.insert_change(tree.conn, change)

    report = tree.changes.recover()

    assert report == ChangeRecovery()
    assert tree.states() == [("pending", None, 0)]


def test_nothing_to_recover_is_an_empty_report(tree: Tree) -> None:
    write(tree.user, "app", APP)
    tree.changes.disable(tree.item())

    assert tree.changes.recover() == ChangeRecovery()
    assert tree.states() == [("done", None, 1)]


def test_changes_are_allowed_again_once_recovered(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tree.user, "app", APP)
    item = interrupted(tree, monkeypatch, "disable", "replace")
    tree.changes.recover()

    result = tree.changes.disable(item)

    assert (result.change_id, result.state, result.refusal) == (2, ChangeState.DONE, None)
