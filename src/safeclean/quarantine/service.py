"""Quarantine service: journal before move, same-device rename, atomic batch (decision 0004).

Per operation:

1. every candidate passes preflight; refused ones are reported and left alone, the rest form
   one batch; a file on another device than the vault is refused (``CROSS_DEVICE``);
2. the operation and all its items are committed as ``pending`` *before* anything moves;
3. each file is renamed into its vault slot and marked ``quarantined``;
4. if a move fails, moved files are renamed back, never over a file that appeared at the
   original path meanwhile. The operation becomes ``rolled_back``, or ``failed`` when some
   file had to stay in the vault (it remains ``quarantined`` and restorable).

``restore()`` puts quarantined files back with their journaled mode, atime and mtime. It never
overwrites (``CONFLICT``), recreates missing parent directories, refuses a parent chain that now
contains a link, and treats a missing or changed vault copy as ``lost``. Items are independent:
one failure does not undo the others (unlike the atomic quarantine batch, decision 0007).

Race window: the ``CONFLICT`` check and the rename are two steps, and ``Path.replace``
overwrites. A file created at the original path in between would be replaced. The standard
library offers no no-replace rename (``renameat2(RENAME_NOREPLACE)``); the window is accepted
and kept as short as possible: the check runs immediately before the move.

``plan_purge()`` reads the journal only and returns a plan to confirm; ``purge()`` accepts that
exact plan once, from the service that issued it, and deletes vault copies through
``purge.delete_from_vault``, the only deletion point (decision 0008). A changed vault copy is
never deleted; the original path is never touched.

``recover()`` reconciles what a crash left behind (``pending`` quarantine items, and quarantined
items of a ``pending`` restore or purge); until it has run, new operations are refused. A vault
copy that no longer matches the journaled size/``mtime_ns`` is not ours to restore or purge: it
becomes ``lost`` and is reported loudly.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path

from safeclean.core.heuristics import JunkClassifier
from safeclean.core.open_files import OpenFileChecker
from safeclean.core.policy import PathPolicy
from safeclean.quarantine.preflight import Candidate, Cleared, Preflight, RefusalReason, Refused
from safeclean.quarantine.purge import delete_from_vault
from safeclean.quarantine.vault import Vault
from safeclean.storage.pending import has_pending
from safeclean.storage.transactions import transaction

Move = Callable[[Path, Path], object]
Delete = Callable[[Path, Path], object]  # (vault root, slot)


class QuarantineError(Exception):
    """The quarantine cannot run safely (vault location, unrecovered journal)."""


class PurgeError(QuarantineError):
    """The purge plan was not issued by this service, was altered, or was already used."""


class OperationState(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ItemState(StrEnum):
    PENDING = "pending"
    QUARANTINED = "quarantined"
    RESTORED = "restored"
    ROLLED_BACK = "rolled_back"
    LOST = "lost"
    PURGED = "purged"


class RestoreRefusal(StrEnum):
    UNKNOWN_ITEM = "unknown_item"
    DUPLICATE_ITEM = "duplicate_item"  # same id twice in one call
    NOT_QUARANTINED = "not_quarantined"  # restored, rolled back, lost or purged
    VAULT_MISSING = "vault_missing"  # item becomes lost
    VAULT_CHANGED = "vault_changed"  # item becomes lost (decision 0006)
    CONFLICT = "conflict"  # something occupies the original path: never overwritten
    PARENT_SWAPPED = "parent_swapped"  # a directory on the original path is now a link
    MOVE_FAILED = "move_failed"  # OS error; the item stays quarantined


class PurgeRefusal(StrEnum):
    UNKNOWN_ITEM = "unknown_item"
    DUPLICATE_ITEM = "duplicate_item"
    NOT_QUARANTINED = "not_quarantined"
    VAULT_MISSING = "vault_missing"  # item becomes lost
    VAULT_CHANGED = "vault_changed"  # item becomes lost; the copy is NOT deleted
    DELETE_FAILED = "delete_failed"  # OS error; the item stays quarantined


@dataclass(frozen=True)
class Moved:
    item_id: int
    original: Path
    vault_path: Path


@dataclass(frozen=True)
class QuarantineResult:
    operation_id: int | None  # None: everything was refused, nothing journaled
    state: OperationState | None
    moved: tuple[Moved, ...]  # files in the vault when the call returns
    refused: tuple[Refused, ...]
    error: str = ""


@dataclass(frozen=True)
class Restored:
    item_id: int
    original: Path


@dataclass(frozen=True)
class RestoreRefused:
    item_id: int
    reason: RestoreRefusal
    detail: str = ""


@dataclass(frozen=True)
class RestoreResult:
    operation_id: int | None  # None: everything was refused before journaling
    state: OperationState | None
    restored: tuple[Restored, ...]
    refused: tuple[RestoreRefused, ...]


@dataclass(frozen=True)
class PlannedPurge:
    item_id: int
    original: Path
    size: int


@dataclass(frozen=True)
class PurgeRefused:
    item_id: int
    reason: PurgeRefusal
    detail: str = ""


@dataclass(frozen=True)
class PurgePlan:
    """What the user confirms. Accepted once, unchanged, by the service that issued it."""

    token: str
    items: tuple[PlannedPurge, ...]
    refused: tuple[PurgeRefused, ...]

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.items)


@dataclass(frozen=True)
class PurgeResult:
    operation_id: int | None  # None: nothing left to purge, nothing journaled
    state: OperationState | None
    purged: tuple[PlannedPurge, ...]
    refused: tuple[PurgeRefused, ...]

    @property
    def freed_bytes(self) -> int:
        return sum(item.size for item in self.purged)


@dataclass(frozen=True)
class RecoveryReport:
    quarantined: tuple[Path, ...] = ()
    rolled_back: tuple[Path, ...] = ()
    restored: tuple[Path, ...] = ()
    purged: tuple[Path, ...] = ()
    lost: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()  # one per lost item; must be shown to the user


@dataclass(frozen=True)
class _Journaled:
    """A quarantined item as the journal knows it."""

    item_id: int
    original: Path
    slot: Path
    size: int
    mtime_ns: int
    mode: int
    atime_ns: int | None


# (item id, reason value, detail): a refusal common to restore and purge.
_Rejected = tuple[int, str, str]


class QuarantineService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        policy: PathPolicy,
        open_files: OpenFileChecker,
        classifier: JunkClassifier,
        move: Move = Path.replace,
        vault: Vault | None = None,
        delete: Delete = delete_from_vault,
    ) -> None:
        self._preflight = Preflight(policy, open_files)
        data_dir = check_data_dir(policy, classifier)
        self._conn = conn
        self._move = move
        self._delete = delete
        self._plans: dict[str, PurgePlan] = {}
        self._vault = vault or Vault(data_dir)
        self._vault.ensure()

    # --- quarantine ----------------------------------------------------------------------------

    def quarantine(self, candidates: Sequence[Candidate]) -> QuarantineResult:
        self._require_no_pending()
        cleared, refused = self._check(candidates)
        if not cleared:
            return QuarantineResult(None, None, (), refused)
        operation_id, items = self._journal(cleared)
        moved: list[Moved] = []
        try:
            self._vault.prepare(operation_id)
            for item in items:
                self._move(item.original, item.vault_path)
                moved.append(item)  # before the journal update: rollback must see it
                self._set_item(item.item_id, ItemState.QUARANTINED)
        except BaseException as error:
            kept = self._roll_back(items, moved)
            state = OperationState.FAILED if kept else OperationState.ROLLED_BACK
            message = str(error) or type(error).__name__
            self._finish(operation_id, state, message)
            if not isinstance(error, OSError):
                raise
            return QuarantineResult(operation_id, state, kept, refused, message)
        self._finish(operation_id, OperationState.DONE, None)
        return QuarantineResult(operation_id, OperationState.DONE, tuple(moved), refused)

    def _check(self, candidates: Sequence[Candidate]) -> tuple[list[Cleared], tuple[Refused, ...]]:
        device = self._vault.device()
        cleared: list[Cleared] = []
        refused: list[Refused] = []
        seen: set[Path] = set()
        for candidate in candidates:
            path = candidate.entry.path
            if path in seen:
                refused.append(Refused(path, RefusalReason.DUPLICATE_CANDIDATE))
                continue
            seen.add(path)
            result = self._preflight.check(candidate)
            if isinstance(result, Refused):
                refused.append(result)
            elif result.stat.st_dev != device:
                refused.append(Refused(path, RefusalReason.CROSS_DEVICE))
            else:
                cleared.append(result)
        return cleared, tuple(refused)

    def _journal(self, cleared: list[Cleared]) -> tuple[int, list[Moved]]:
        """Commit the operation and its items as pending; nothing has moved yet."""
        items: list[Moved] = []
        with transaction(self._conn):
            operation_id = _insert(
                self._conn,
                "INSERT INTO operations (kind, state, created_at_ns) VALUES ('quarantine', ?, ?)",
                (OperationState.PENDING, time.time_ns()),
            )
            for index, entry in enumerate(cleared):
                original = entry.candidate.entry.path
                # The slot name is the item id, known only after the insert: write a unique
                # placeholder, then the real slot, in the same transaction.
                item_id = _insert(
                    self._conn,
                    "INSERT INTO items (operation_id, original_path, vault_path, size, mtime_ns,"
                    " atime_ns, mode, digest, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        operation_id,
                        str(original),
                        f"pending:{operation_id}:{index}",
                        entry.stat.st_size,
                        entry.stat.st_mtime_ns,
                        entry.stat.st_atime_ns,
                        entry.stat.st_mode,
                        entry.candidate.digest,
                        ItemState.PENDING,
                    ),
                )
                slot = self._vault.slot(operation_id, item_id)
                self._conn.execute(
                    "UPDATE items SET vault_path = ? WHERE id = ?", (str(slot), item_id)
                )
                items.append(Moved(item_id, original, slot))
        return operation_id, items

    def _roll_back(self, items: list[Moved], moved: list[Moved]) -> tuple[Moved, ...]:
        """Move files back, newest first. Returns the items that had to stay in the vault.

        An interrupt can land between a completed rename and ``moved.append``: an item whose
        slot exists is treated as moved, whatever the in-memory list says (decision 0006).
        """
        moved_ids = {item.item_id for item in moved}
        landed = moved + [
            item for item in items if item.item_id not in moved_ids and _exists(item.vault_path)
        ]
        kept: list[Moved] = []
        for item in reversed(landed):
            if self._move_back(item):
                self._set_item(item.item_id, ItemState.ROLLED_BACK)
            else:
                kept.append(item)
        landed_ids = {item.item_id for item in landed}
        for item in items:
            if item.item_id not in landed_ids:
                self._set_item(item.item_id, ItemState.ROLLED_BACK)
        return tuple(reversed(kept))

    def _move_back(self, item: Moved) -> bool:
        if _exists(item.original):
            return False  # a newcomer took the original path: never overwrite it
        try:
            self._move(item.vault_path, item.original)
        except OSError:
            return False
        return True

    # --- restore -------------------------------------------------------------------------------

    def restore(self, item_ids: Sequence[int]) -> RestoreResult:
        self._require_no_pending()
        accepted, refused = self._select_for_restore(item_ids)
        if not accepted:
            return RestoreResult(None, None, (), tuple(refused))
        operation_id = self._journal_side_operation("restore", "restore_operation_id", accepted)
        restored: list[Restored] = []
        for item in accepted:
            refusal = self._restore_one(item)
            if refusal is None:
                restored.append(Restored(item.item_id, item.original))
            else:
                refused.append(refusal)
        state = _outcome(len(restored), len(accepted))
        error = None if state is OperationState.DONE else "some items were not restored"
        self._finish(operation_id, state, error)
        return RestoreResult(operation_id, state, tuple(restored), tuple(refused))

    def _select_for_restore(
        self, item_ids: Sequence[int]
    ) -> tuple[list[_Journaled], list[RestoreRefused]]:
        accepted, refused = self._select(item_ids)
        return accepted, [RestoreRefused(i, RestoreRefusal(r), d) for i, r, d in refused]

    def _select(self, item_ids: Sequence[int]) -> tuple[list[_Journaled], list[_Rejected]]:
        """Refusals that do not depend on the disk, before anything is journaled."""
        accepted: list[_Journaled] = []
        refused: list[_Rejected] = []
        seen: set[int] = set()
        for item_id in item_ids:
            if item_id in seen:
                refused.append((item_id, "duplicate_item", ""))
                continue
            seen.add(item_id)
            row = self._conn.execute(
                "SELECT state, original_path, vault_path, size, mtime_ns, mode, atime_ns"
                " FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                refused.append((item_id, "unknown_item", ""))
            elif row[0] != ItemState.QUARANTINED:
                refused.append((item_id, "not_quarantined", row[0]))
            else:
                _, original, slot, size, mtime_ns, mode, atime_ns = row
                accepted.append(
                    _Journaled(item_id, Path(original), Path(slot), size, mtime_ns, mode, atime_ns)
                )
        return accepted, refused

    def _journal_side_operation(self, kind: str, column: str, items: list[_Journaled]) -> int:
        """Journal a restore or purge as pending and link its items, before touching the disk."""
        with transaction(self._conn):
            operation_id = _insert(
                self._conn,
                "INSERT INTO operations (kind, state, created_at_ns) VALUES (?, ?, ?)",
                (kind, OperationState.PENDING, time.time_ns()),
            )
            self._conn.executemany(
                f"UPDATE items SET {column} = ? WHERE id = ?",
                [(operation_id, item.item_id) for item in items],
            )
        return operation_id

    def _restore_one(self, item: _Journaled) -> RestoreRefused | None:
        """Disk checks right before the move, then the move. None means restored."""
        copy = _probe(item.slot, item.size, item.mtime_ns)
        if copy is not _Copy.MATCHES:
            self._set_item(item.item_id, ItemState.LOST)
            missing = copy is _Copy.MISSING
            reason = RestoreRefusal.VAULT_MISSING if missing else RestoreRefusal.VAULT_CHANGED
            return RestoreRefused(item.item_id, reason, str(item.slot))
        parent = item.original.parent
        if parent.resolve() != parent:
            return RestoreRefused(item.item_id, RestoreRefusal.PARENT_SWAPPED, str(parent))
        if _exists(item.original):
            return RestoreRefused(item.item_id, RestoreRefusal.CONFLICT, str(item.original))
        try:
            parent.mkdir(parents=True, exist_ok=True)
            # Metadata goes onto the vault copy first; the rename carries it over unchanged.
            item.slot.chmod(stat.S_IMODE(item.mode))
            atime_ns = item.atime_ns if item.atime_ns is not None else item.slot.lstat().st_atime_ns
            os.utime(item.slot, ns=(atime_ns, item.mtime_ns))
            self._move(item.slot, item.original)
        except OSError as error:
            return RestoreRefused(item.item_id, RestoreRefusal.MOVE_FAILED, str(error))
        self._set_item(item.item_id, ItemState.RESTORED)
        return None

    # --- purge ---------------------------------------------------------------------------------

    def plan_purge(self, item_ids: Sequence[int]) -> PurgePlan:
        """Read-only: what ``purge`` would delete, for the user to confirm."""
        self._require_no_pending()
        accepted, refused = self._select_for_purge(item_ids)
        planned = tuple(PlannedPurge(i.item_id, i.original, i.size) for i in accepted)
        plan = PurgePlan(secrets.token_hex(16), planned, tuple(refused))
        self._plans[plan.token] = plan
        return plan

    def purge(self, plan: PurgePlan) -> PurgeResult:
        if self._plans.pop(plan.token, None) != plan:  # one use; a tampered plan burns it too
            raise PurgeError("unknown, altered or already used purge plan; plan again")
        self._require_no_pending()
        accepted, refused = self._select_for_purge([item.item_id for item in plan.items])
        refused = [*plan.refused, *refused]
        if not accepted:
            return PurgeResult(None, None, (), tuple(refused))
        operation_id = self._journal_side_operation("purge", "purge_operation_id", accepted)
        purged: list[PlannedPurge] = []
        for item in accepted:
            refusal = self._purge_one(item)
            if refusal is None:
                purged.append(PlannedPurge(item.item_id, item.original, item.size))
            else:
                refused.append(refusal)
        state = _outcome(len(purged), len(accepted))
        error = None if state is OperationState.DONE else "some items were not purged"
        self._finish(operation_id, state, error)
        return PurgeResult(operation_id, state, tuple(purged), tuple(refused))

    def _select_for_purge(
        self, item_ids: Sequence[int]
    ) -> tuple[list[_Journaled], list[PurgeRefused]]:
        accepted, refused = self._select(item_ids)
        return accepted, [PurgeRefused(i, PurgeRefusal(r), d) for i, r, d in refused]

    def _purge_one(self, item: _Journaled) -> PurgeRefused | None:
        copy = _probe(item.slot, item.size, item.mtime_ns)
        if copy is not _Copy.MATCHES:
            self._set_item(item.item_id, ItemState.LOST)
            missing = copy is _Copy.MISSING
            reason = PurgeRefusal.VAULT_MISSING if missing else PurgeRefusal.VAULT_CHANGED
            return PurgeRefused(item.item_id, reason, str(item.slot))
        try:
            self._delete(self._vault.root, item.slot)
        except OSError as error:
            return PurgeRefused(item.item_id, PurgeRefusal.DELETE_FAILED, str(error))
        self._set_item(item.item_id, ItemState.PURGED)
        return None

    # --- recover -------------------------------------------------------------------------------

    def recover(self) -> RecoveryReport:
        """Reconcile pending items with the disk, then close their operations."""
        found: dict[ItemState, list[Path]] = {state: [] for state in ItemState}
        warnings: list[str] = []
        pending = self._conn.execute(
            "SELECT id, original_path, vault_path, size, mtime_ns FROM items"
            " WHERE state = ? ORDER BY id",
            (ItemState.PENDING,),
        ).fetchall()
        for item_id, original_text, vault_text, size, mtime_ns in pending:
            original, slot = Path(original_text), Path(vault_text)
            copy = _probe(slot, size, mtime_ns)
            if copy is _Copy.MATCHES:
                state = ItemState.QUARANTINED
            elif copy is _Copy.CHANGED:
                state = ItemState.LOST
                warnings.append(
                    f"LOST: the vault copy of {original} changed after the move ({slot});"
                    " it will not be restored or purged"
                )
            elif _exists(original):
                state = ItemState.ROLLED_BACK
            else:
                state = ItemState.LOST
                warnings.append(f"LOST: {original} is neither at its path nor in the vault")
            self._set_item(item_id, state)
            found[state].append(original)
        rolling_back = self._conn.execute(
            "SELECT items.id, original_path, vault_path, size, mtime_ns FROM items"
            " JOIN operations ON items.operation_id = operations.id"
            " WHERE operations.state = ? AND items.state = ? ORDER BY items.id",
            (OperationState.PENDING, ItemState.QUARANTINED),
        ).fetchall()
        for item_id, original_text, vault_text, size, mtime_ns in rolling_back:
            # Interrupted during rollback: the move back may have happened unrecorded.
            original, slot = Path(original_text), Path(vault_text)
            copy = _probe(slot, size, mtime_ns)
            if copy is _Copy.MATCHES:
                continue  # still in the vault: stays quarantined, not reported again
            if copy is _Copy.MISSING and _probe(original, size, mtime_ns) is _Copy.MATCHES:
                state = ItemState.ROLLED_BACK
            else:
                state = ItemState.LOST
                warnings.append(f"LOST: {original} is neither at its path nor intact in the vault")
            self._set_item(item_id, state)
            found[state].append(original)
        restoring = self._conn.execute(
            "SELECT items.id, original_path, vault_path, size, mtime_ns FROM items"
            " JOIN operations ON items.restore_operation_id = operations.id"
            " WHERE operations.state = ? AND items.state = ? ORDER BY items.id",
            (OperationState.PENDING, ItemState.QUARANTINED),
        ).fetchall()
        for item_id, original_text, vault_text, size, mtime_ns in restoring:
            original, slot = Path(original_text), Path(vault_text)
            copy = _probe(slot, size, mtime_ns)
            if copy is _Copy.MATCHES:
                state = ItemState.QUARANTINED  # the move never happened
            elif copy is _Copy.MISSING and _probe(original, size, mtime_ns) is _Copy.MATCHES:
                state = ItemState.RESTORED  # moved, journal update lost
            else:
                state = ItemState.LOST
                warnings.append(
                    f"LOST: {original} is neither back at its path nor intact in the vault"
                )
            self._set_item(item_id, state)
            found[state].append(original)
        purging = self._conn.execute(
            "SELECT items.id, original_path, vault_path, size, mtime_ns FROM items"
            " JOIN operations ON items.purge_operation_id = operations.id"
            " WHERE operations.state = ? AND items.state = ? ORDER BY items.id",
            (OperationState.PENDING, ItemState.QUARANTINED),
        ).fetchall()
        for item_id, original_text, vault_text, size, mtime_ns in purging:
            original, slot = Path(original_text), Path(vault_text)
            copy = _probe(slot, size, mtime_ns)
            if copy is _Copy.MATCHES:
                state = ItemState.QUARANTINED  # the delete never happened
            elif copy is _Copy.MISSING:
                state = ItemState.PURGED  # deleted, journal update lost
            else:
                state = ItemState.LOST
                warnings.append(
                    f"LOST: the vault copy of {original} changed during a purge ({slot});"
                    " it was not deleted"
                )
            self._set_item(item_id, state)
            found[state].append(original)
        self._close_pending_operations()
        return RecoveryReport(
            quarantined=tuple(found[ItemState.QUARANTINED]),
            rolled_back=tuple(found[ItemState.ROLLED_BACK]),
            restored=tuple(found[ItemState.RESTORED]),
            purged=tuple(found[ItemState.PURGED]),
            lost=tuple(found[ItemState.LOST]),
            warnings=tuple(warnings),
        )

    def _close_pending_operations(self) -> None:
        operations = self._conn.execute(
            "SELECT id, kind FROM operations WHERE state = ?", (OperationState.PENDING,)
        ).fetchall()
        for operation_id, kind in operations:
            column, done, undone = _OPERATION_ITEMS[kind]
            states = {
                ItemState(state)
                for (state,) in self._conn.execute(
                    f"SELECT state FROM items WHERE {column} = ?", (operation_id,)
                )
            }
            if states <= {done}:
                self._finish(operation_id, OperationState.DONE, None)
            elif states == {undone}:
                self._finish(operation_id, OperationState.ROLLED_BACK, "interrupted; recovered")
            else:
                self._finish(operation_id, OperationState.FAILED, "interrupted; recovered")

    # --- journal helpers -----------------------------------------------------------------------

    def _require_no_pending(self) -> None:
        if self._has_pending():
            raise QuarantineError("the journal has unfinished work; run recover() first")

    def _has_pending(self) -> bool:
        return has_pending(self._conn)  # autostart changes too (decision 0011, item 62)

    def _set_item(self, item_id: int, state: ItemState) -> None:
        with transaction(self._conn):
            self._conn.execute("UPDATE items SET state = ? WHERE id = ?", (state, item_id))

    def _finish(self, operation_id: int, state: OperationState, error: str | None) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE operations SET state = ?, finished_at_ns = ?, error = ? WHERE id = ?",
                (state, time.time_ns(), error, operation_id),
            )


def check_data_dir(policy: PathPolicy, classifier: JunkClassifier) -> Path:
    """The data directory (journal and vault) must never be something a scan would offer.

    Callers run it before creating anything there (decision 0009).
    """
    data_dir = Path(policy.app_data_dir)
    for root in policy.default_roots():
        if data_dir.is_relative_to(root):
            raise QuarantineError(f"data directory {data_dir} is inside scan zone {root}")
    match = classifier.classify(data_dir / "quarantine" / "0" / "0")
    if match is not None:
        raise QuarantineError(f"data directory {data_dir} matches junk rule {match.rule_id}")
    return data_dir


# Per operation kind: the items column linking to it, the item state when the operation
# completed, and the item state when it did not happen at all.
_OPERATION_ITEMS: dict[str, tuple[str, ItemState, ItemState]] = {
    "quarantine": ("operation_id", ItemState.QUARANTINED, ItemState.ROLLED_BACK),
    "restore": ("restore_operation_id", ItemState.RESTORED, ItemState.QUARANTINED),
    "purge": ("purge_operation_id", ItemState.PURGED, ItemState.QUARANTINED),
}


def _outcome(succeeded: int, attempted: int) -> OperationState:
    if succeeded == attempted:
        return OperationState.DONE
    return OperationState.FAILED if succeeded else OperationState.ROLLED_BACK


class _Copy(Enum):
    MATCHES = "matches"
    CHANGED = "changed"
    MISSING = "missing"


def _probe(path: Path, size: int, mtime_ns: int) -> _Copy:
    """Is the file at ``path`` the one we journaled (regular, same size and mtime_ns)?"""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return _Copy.MISSING
    same = (info.st_size, info.st_mtime_ns) == (size, mtime_ns)
    return _Copy.MATCHES if stat.S_ISREG(info.st_mode) and same else _Copy.CHANGED


def _insert(conn: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> int:
    rowid = conn.execute(sql, params).lastrowid
    if rowid is None:  # pragma: no cover - sqlite3 always sets it after a successful INSERT
        raise QuarantineError("journal insert returned no row id")
    return rowid


def _exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True
