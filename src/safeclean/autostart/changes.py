"""Disabling and enabling XDG autostart entries, journaled first (0011, items 66-79, 93-98).

Disable, a user's own entry: the copy with ``Hidden=true`` is staged in the autostart store,
the original is linked into the store (same inode) and the copy atomically replaces it, so the
entry is never missing. Disable, a system entry: a stub is created in the user directory with
``O_EXCL``; ``/etc`` is never written. Enable puts the original back (the copy is kept in the
store) only if the journal shows safeclean disabled it; a stub is moved to the store. Each
change is a ``pending`` row of ``autostart_changes`` before the disk is touched; a failure
rolls it back, and nothing is ever deleted. Refusals change nothing and journal nothing.
The journal of these changes (``autostart.journal``) is shared with ``run_changes`` (item 81).
``recover()`` closes pending changes, and failed ones still last at their place, by the disk.
"""

from __future__ import annotations

import contextlib
import functools
import os
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from safeclean.autostart.entries import BrokenEntryError, decode, read_entry
from safeclean.autostart.journal import (
    Change,
    ChangeRecovery,
    ChangeRefusal,
    ChangeResult,
    ChangeState,
    finish_change,
    insert_change,
    refused,
)
from safeclean.autostart.models import AutostartItem, Scope, Source, entry_digest
from safeclean.autostart.xdg import parse_keys, read_xdg
from safeclean.autostart.xdg_changes import STUB, hidden_copy
from safeclean.storage.data_dir import PRIVATE
from safeclean.storage.journal import Clock
from safeclean.storage.pending import has_pending
from safeclean.storage.transactions import transaction

ENTRY_MODE = 0o644
_AS_BEFORE = "the entry is as it was before the change"
_NEITHER = "the entry is neither as before nor as after the change"
_NOT_KEPT = "the entry is as after the change, but the store does not hold what it kept"
_PARTIAL = "a partial stub was moved to the store"
_NOTHING_THERE = (FileNotFoundError, NotADirectoryError)  # every other error: something is there


class AutostartStore:
    """``<data_dir>/autostart/<change id>``: originals and removed stubs, never purged; made by
    the first change, right before it is journaled (item 115)."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.root = data_dir / "autostart"

    def ensure(self) -> None:
        self.root.mkdir(mode=PRIVATE, parents=True, exist_ok=True)
        self.root.chmod(PRIVATE)

    def device(self) -> int:
        """Of the store, or of the directory above it where it will be made."""
        return _device(self.root)

    def slot(self, change_id: int) -> Path:
        return self.root / str(change_id)

    def staging(self, change_id: int) -> Path:
        return self.root / f"{change_id}.new"


@dataclass(frozen=True)
class _Plan:
    action: str
    entry: Path  # as listed
    location: Path  # what is written
    before: bytes | None  # None: nothing there
    after: bytes | None  # None: nothing there afterwards
    steps: Callable[[int, _Plan], None]  # given the change id
    stores: bool  # the slot of this change is its vault_path from the start


@dataclass(frozen=True)
class _Disabled:
    original: bytes
    copy: bytes
    slot: Path  # where the original is kept


class XdgChanges:
    def __init__(
        self,
        conn: sqlite3.Connection,
        store: AutostartStore,
        user_dir: Path,
        system_dirs: Sequence[Path],
        *,
        now: Clock = time.time_ns,
    ) -> None:
        self._conn = conn
        self._store = store
        self._user_dir = user_dir
        self._system_dirs = tuple(system_dirs)
        self._now = now

    def disable(self, item: AutostartItem) -> ChangeResult:
        raw = self._check(item, enabled=True)
        if isinstance(raw, ChangeResult):
            return raw
        location = Path(item.location)
        if item.scope is Scope.SYSTEM:
            stub = self._user_dir / location.name
            plan = _Plan("disable", location, stub, None, STUB, self._create_stub, stores=False)
        else:
            try:
                copy = hidden_copy(raw)
            except BrokenEntryError as error:
                return refused(ChangeRefusal.TOO_LARGE, str(error))
            steps = functools.partial(self._replace, copy)
            plan = _Plan("disable", location, location, raw, copy, steps, stores=True)
        return self._apply(item, plan)

    def enable(self, item: AutostartItem) -> ChangeResult:
        raw = self._check(item, enabled=False)
        if isinstance(raw, ChangeResult):
            return raw
        location = Path(item.location)
        if "Exec" not in parse_keys(decode(raw)):  # a stub: moved, never edited (item 74)
            plan = _Plan("enable", location, location, raw, None, self._remove_stub, stores=True)
            return self._apply(item, plan)
        disabled = self._disabled_here(location)
        if disabled is None or disabled.copy != raw:
            detail = "not disabled by safeclean; enabling it would edit its content"
            return refused(ChangeRefusal.FOREIGN, detail)
        if _read(disabled.slot) != disabled.original:
            detail = f"the original in {disabled.slot} is missing or changed"
            return refused(ChangeRefusal.ORIGINAL_CHANGED, detail)
        steps = functools.partial(self._restore, disabled.slot)
        plan = _Plan("enable", location, location, raw, disabled.original, steps, stores=True)
        return self._apply(item, plan)

    def recover(self) -> ChangeRecovery:
        """Close pending XDG changes, and failed ones still last at their place, by the disk."""
        rows = self._conn.execute(
            "SELECT id, location, value_before, value_after, vault_path, state"
            " FROM autostart_changes AS c WHERE source = ? AND state IN (?, ?)"
            " AND NOT EXISTS (SELECT 1 FROM autostart_changes AS later"
            " WHERE later.location = c.location AND later.id > c.id) ORDER BY id",
            (Source.XDG_AUTOSTART.value, ChangeState.PENDING.value, ChangeState.FAILED.value),
        ).fetchall()
        closed: dict[ChangeState, list[int]] = {
            ChangeState.DONE: [],
            ChangeState.ROLLED_BACK: [],
            ChangeState.FAILED: [],
        }
        for change_id, location, before, after, vault_path, was in rows:
            state, error = self._reconcile(change_id, Path(location), before, after, vault_path)
            if state is ChangeState.FAILED and was == ChangeState.FAILED.value:
                continue  # still failed: its first error is kept
            self._finish(change_id, state, error)
            closed[state].append(change_id)
        return ChangeRecovery(
            tuple(closed[ChangeState.DONE]),
            tuple(closed[ChangeState.ROLLED_BACK]),
            tuple(closed[ChangeState.FAILED]),
        )

    def _reconcile(
        self,
        change_id: int,
        location: Path,
        before: bytes | None,
        after: bytes | None,
        vault_path: str | None,
    ) -> tuple[ChangeState, str | None]:
        """How the disk shows the change ended; a partial stub is moved to the store."""
        found = _current(location)
        if found == after:
            if vault_path is None or _current(Path(vault_path)) == before:
                return ChangeState.DONE, None
            return ChangeState.FAILED, _NOT_KEPT
        if found == before:
            return ChangeState.ROLLED_BACK, _AS_BEFORE
        if before is None and after == STUB and found is not None and STUB.startswith(found):
            slot = self._store.slot(change_id)
            with transaction(self._conn):  # journaled before it is moved
                self._set_vault_path(change_id, slot)
            location.rename(slot)
            return ChangeState.ROLLED_BACK, _PARTIAL
        return ChangeState.FAILED, _NEITHER

    def _check(self, item: AutostartItem, *, enabled: bool) -> bytes | ChangeResult:
        """The entry's bytes, read once, if it may change; else the refusal."""
        if item.source is not Source.XDG_AUTOSTART:
            return refused(ChangeRefusal.READ_ONLY, f"{item.source} entries are read-only")
        if self._has_pending():
            detail = "the journal has unfinished work; run recover() first"
            return refused(ChangeRefusal.PENDING, detail)
        if item not in read_xdg(self._user_dir, self._system_dirs).items:
            return refused(ChangeRefusal.CHANGED, "the entry changed since it was listed")
        if item.enabled is not enabled:
            state = "enabled" if item.enabled else "disabled"
            return refused(ChangeRefusal.ALREADY, f"the entry is already {state}")
        raw = _read(Path(item.location))  # once: what is journaled is what was compared
        if raw is None or entry_digest(raw) != item.digest:
            return refused(ChangeRefusal.CHANGED, "the entry changed since it was listed")
        return raw

    def _apply(self, item: AutostartItem, plan: _Plan) -> ChangeResult:
        if _device(plan.location.parent) != self._store.device():
            return refused(ChangeRefusal.OTHER_DEVICE, "the store is on another device")
        self._store.ensure()  # every journaled change has its store
        change_id = self._journal(item, plan)
        try:
            plan.steps(change_id, plan)
        except BaseException as error:
            message = str(error) or type(error).__name__
            # Rolled back only if the disk is as it was, or if a step found its place taken:
            # nothing of ours was written then (item 117). Anything left is for recover().
            restored = isinstance(error, FileExistsError) or _read(plan.location) == plan.before
            state = ChangeState.ROLLED_BACK if restored else ChangeState.FAILED
            self._finish(change_id, state, message)
            if not isinstance(error, OSError):
                raise
            return ChangeResult(change_id, state, None, message)
        self._finish(change_id, ChangeState.DONE, None)
        return ChangeResult(change_id, ChangeState.DONE)

    def _replace(self, copy: bytes, change_id: int, plan: _Plan) -> None:
        """Disable an own entry: stage the copy, link the original into the store, swap."""
        staging = self._store.staging(change_id)
        _write_new(staging, copy)
        self._store.slot(change_id).hardlink_to(plan.location)
        staging.replace(plan.location)

    def _restore(self, original: Path, change_id: int, plan: _Plan) -> None:
        """Enable an own entry: link the copy into the store, move the original back."""
        self._store.slot(change_id).hardlink_to(plan.location)
        original.replace(plan.location)

    def _remove_stub(self, change_id: int, plan: _Plan) -> None:
        """Enable a stub over a system entry: moved to the store, never edited."""
        plan.location.rename(self._store.slot(change_id))

    def _create_stub(self, change_id: int, plan: _Plan) -> None:
        stub = plan.location
        with contextlib.suppress(FileExistsError):  # an existing directory keeps its mode
            self._user_dir.mkdir(mode=PRIVATE, parents=True)
        fd = os.open(stub, os.O_WRONLY | os.O_CREAT | os.O_EXCL, ENTRY_MODE)
        try:
            _write_and_close(fd, STUB)
        except BaseException:
            slot = self._store.slot(change_id)
            with transaction(self._conn):  # journaled before it is moved, as in recover()
                self._set_vault_path(change_id, slot)
            stub.rename(slot)  # a partial stub is kept, never deleted
            raise

    def _journal(self, item: AutostartItem, plan: _Plan) -> int:
        change = Change(
            plan.action,
            item.source,
            str(plan.entry),
            str(plan.location),
            item.digest,
            plan.before,
            plan.after,
        )
        with transaction(self._conn):
            change_id = insert_change(self._conn, change, now=self._now)
            if plan.stores:
                self._set_vault_path(change_id, self._store.slot(change_id))
        return change_id

    def _set_vault_path(self, change_id: int, slot: Path) -> None:
        self._conn.execute(
            "UPDATE autostart_changes SET vault_path = ? WHERE id = ?", (str(slot), change_id)
        )

    def _finish(self, change_id: int, state: ChangeState, error: str | None) -> None:
        finish_change(self._conn, change_id, state, error, now=self._now)

    def _disabled_here(self, location: Path) -> _Disabled | None:
        """The disable of an own entry, if it is the last change done at ``location``."""
        row = self._conn.execute(
            "SELECT action, value_before, value_after, vault_path FROM autostart_changes"
            " WHERE location = ? AND state = ? ORDER BY id DESC LIMIT 1",
            (str(location), ChangeState.DONE.value),
        ).fetchone()
        if row is None or row[0] != "disable" or row[3] is None:  # never, or a stub's
            return None
        return _Disabled(original=row[1], copy=row[2], slot=Path(row[3]))

    def _has_pending(self) -> bool:
        return has_pending(self._conn)


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


def _current(path: Path) -> bytes | None:
    """The entry's bytes; ``None`` only if nothing is there: an unreadable one raises."""
    try:
        return read_entry(path)
    except BrokenEntryError:
        if _nothing_at(path):
            return None
        raise


def _nothing_at(path: Path) -> bool:
    """Only ``ENOENT`` and ``ENOTDIR`` say so (item 111): since Python 3.14 ``Path.exists()``
    is ``False`` for any error, so a file that cannot be looked at would seem missing."""
    try:
        path.lstat()
    except _NOTHING_THERE:
        return True
    except OSError:
        return False
    return False


def _device(path: Path) -> int:
    """``st_dev`` of ``path`` or of the nearest directory above it that exists; one that exists
    but cannot be looked at raises, it is not skipped (item 111)."""
    while True:
        try:
            return path.stat().st_dev
        except _NOTHING_THERE:
            path = path.parent
