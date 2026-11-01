"""Disabling XDG autostart entries, journaled before they are made (decision 0011, items 66-74).

A user's own entry: the copy with ``Hidden=true`` is staged in the autostart store, the
original is linked into the store (same inode) and the copy atomically replaces it, so the
entry is never missing. A system entry: a stub is created in the user directory with
``O_EXCL``; ``/etc`` is never written. Each change is a ``pending`` row of
``autostart_changes`` before the disk is touched; a failure rolls it back, and nothing is ever
deleted. Refusals change nothing and journal nothing.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from safeclean.autostart.entries import BrokenEntryError, read_entry
from safeclean.autostart.models import AutostartItem, Scope, Source, entry_digest
from safeclean.autostart.xdg import read_xdg
from safeclean.autostart.xdg_changes import STUB, hidden_copy
from safeclean.storage.transactions import transaction

PRIVATE = 0o700
ENTRY_MODE = 0o644


class ChangeState(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"  # something was left on disk; recover() reconciles it
    ROLLED_BACK = "rolled_back"


class ChangeRefusal(StrEnum):
    READ_ONLY = "read_only"  # a source step 4 does not write (item 9)
    CHANGED = "changed"  # not the entry in effect as it was listed
    ALREADY = "already"  # already disabled
    PENDING = "pending"  # unfinished work in the journal: recover() first
    OTHER_DEVICE = "other_device"  # the store cannot hold the original by a link
    TOO_LARGE = "too_large"  # the disabled copy would be skipped by the reader


@dataclass(frozen=True)
class ChangeResult:
    change_id: int | None  # None when refused
    state: ChangeState | None
    refusal: ChangeRefusal | None = None
    detail: str = ""


class AutostartStore:
    """``<data_dir>/autostart/<change id>``: originals and removed stubs, never purged."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.root = data_dir / "autostart"

    def ensure(self) -> None:
        self.root.mkdir(mode=PRIVATE, parents=True, exist_ok=True)
        self.root.chmod(PRIVATE)

    def device(self) -> int:
        return self.root.stat().st_dev

    def slot(self, change_id: int) -> Path:
        return self.root / str(change_id)

    def staging(self, change_id: int) -> Path:
        return self.root / f"{change_id}.new"


@dataclass(frozen=True)
class _Plan:
    entry: Path  # as listed
    location: Path  # what is written
    before: bytes | None  # None: nothing there
    after: bytes


class XdgChanges:
    def __init__(
        self,
        conn: sqlite3.Connection,
        store: AutostartStore,
        user_dir: Path,
        system_dirs: Sequence[Path],
    ) -> None:
        self._conn = conn
        self._store = store
        self._user_dir = user_dir
        self._system_dirs = tuple(system_dirs)
        store.ensure()

    def disable(self, item: AutostartItem) -> ChangeResult:
        if item.source is not Source.XDG_AUTOSTART:
            return _refused(ChangeRefusal.READ_ONLY, f"{item.source} entries are read-only")
        if self._has_pending():
            detail = "the journal has unfinished work; run recover() first"
            return _refused(ChangeRefusal.PENDING, detail)
        if item not in read_xdg(self._user_dir, self._system_dirs).items:
            return _refused(ChangeRefusal.CHANGED, "the entry changed since it was listed")
        if not item.enabled:
            return _refused(ChangeRefusal.ALREADY, "the entry is already disabled")
        if item.scope is Scope.SYSTEM:
            stub = self._user_dir / Path(item.location).name
            plan = _Plan(Path(item.location), stub, None, STUB)
        else:
            path = Path(item.location)
            raw = _read(path)  # once: the copy is made of the bytes journaled
            if raw is None or entry_digest(raw) != item.digest:
                return _refused(ChangeRefusal.CHANGED, "the entry changed since it was listed")
            try:
                plan = _Plan(path, path, raw, hidden_copy(raw))
            except BrokenEntryError as error:
                return _refused(ChangeRefusal.TOO_LARGE, str(error))
        if _device(plan.location.parent) != self._store.device():
            return _refused(ChangeRefusal.OTHER_DEVICE, "the store is on another device")
        return self._apply(item, plan)

    def _apply(self, item: AutostartItem, plan: _Plan) -> ChangeResult:
        change_id = self._journal(item, plan)
        try:
            if plan.before is None:
                self._create_stub(change_id, plan.location)
            else:
                self._replace(change_id, plan)
        except BaseException as error:
            message = str(error) or type(error).__name__
            # Rolled back only if the disk is as it was; anything left is for recover().
            restored = _read(plan.location) == plan.before
            state = ChangeState.ROLLED_BACK if restored else ChangeState.FAILED
            self._finish(change_id, state, message)
            if not isinstance(error, OSError):
                raise
            return ChangeResult(change_id, state, None, message)
        self._finish(change_id, ChangeState.DONE, None)
        return ChangeResult(change_id, ChangeState.DONE)

    def _replace(self, change_id: int, plan: _Plan) -> None:
        staging = self._store.staging(change_id)
        _write_new(staging, plan.after)
        self._store.slot(change_id).hardlink_to(plan.location)
        staging.replace(plan.location)

    def _create_stub(self, change_id: int, stub: Path) -> None:
        with contextlib.suppress(FileExistsError):  # an existing directory keeps its mode
            self._user_dir.mkdir(mode=PRIVATE, parents=True)
        fd = os.open(stub, os.O_WRONLY | os.O_CREAT | os.O_EXCL, ENTRY_MODE)
        try:
            _write_and_close(fd, STUB)
        except BaseException:
            slot = self._store.slot(change_id)
            stub.rename(slot)  # a partial stub is kept, never deleted
            self._set_vault_path(change_id, slot)
            raise

    def _journal(self, item: AutostartItem, plan: _Plan) -> int:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "INSERT INTO autostart_changes (action, source, entry, location, digest,"
                " value_before, value_after, state, created_at_ns)"
                " VALUES ('disable', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item.source.value,
                    str(plan.entry),
                    str(plan.location),
                    item.digest,
                    plan.before,
                    plan.after,
                    ChangeState.PENDING.value,
                    time.time_ns(),
                ),
            )
            change_id = cursor.lastrowid
            if change_id is None:  # pragma: no cover - sqlite3 always sets it after an INSERT
                raise RuntimeError("no row id after INSERT")
            if plan.before is not None:
                self._set_vault_path(change_id, self._store.slot(change_id))
        return change_id

    def _set_vault_path(self, change_id: int, slot: Path) -> None:
        self._conn.execute(
            "UPDATE autostart_changes SET vault_path = ? WHERE id = ?", (str(slot), change_id)
        )

    def _finish(self, change_id: int, state: ChangeState, error: str | None) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE autostart_changes SET state = ?, finished_at_ns = ?, error = ?"
                " WHERE id = ?",
                (state.value, time.time_ns(), error, change_id),
            )

    def _has_pending(self) -> bool:
        """Unfinished autostart changes or quarantine operations block both (item 62)."""
        row = self._conn.execute(
            "SELECT EXISTS (SELECT 1 FROM autostart_changes WHERE state = 'pending')"
            " OR EXISTS (SELECT 1 FROM operations WHERE state = 'pending')"
        ).fetchone()
        return bool(row[0])


def _write_new(path: Path, data: bytes) -> None:
    _write_and_close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, ENTRY_MODE), data)


def _write_and_close(fd: int, data: bytes) -> None:
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _read(path: Path) -> bytes | None:
    """The entry's bytes; ``None`` if it is missing or cannot be read."""
    try:
        return read_entry(path)
    except BrokenEntryError:
        return None


def _device(path: Path) -> int:
    """``st_dev`` of ``path`` or of the nearest directory above it that exists."""
    while not path.exists():
        path = path.parent
    return path.stat().st_dev


def _refused(refusal: ChangeRefusal, detail: str) -> ChangeResult:
    return ChangeResult(None, None, refusal, detail)
