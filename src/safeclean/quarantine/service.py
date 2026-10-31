"""Quarantine service: journal before move, same-device rename, atomic batch (decision 0004).

Per operation:

1. every candidate passes preflight; refused ones are reported and left alone, the rest form
   one batch; a file on another device than the vault is refused (``CROSS_DEVICE``);
2. the operation and all its items are committed as ``pending`` *before* anything moves;
3. each file is renamed into its vault slot and marked ``quarantined``;
4. if a move fails, moved files are renamed back, never over a file that appeared at the
   original path meanwhile. The operation becomes ``rolled_back``, or ``failed`` when some
   file had to stay in the vault (it remains ``quarantined`` and restorable).

``recover()`` reconciles ``pending`` rows a crash left behind; until it has run, new operations
are refused. A vault copy that no longer matches the journaled size/``mtime_ns`` is not ours to
restore or purge: it becomes ``lost`` and is reported loudly.
"""

from __future__ import annotations

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
from safeclean.quarantine.vault import Vault
from safeclean.storage.transactions import transaction

Move = Callable[[Path, Path], object]


class QuarantineError(Exception):
    """The quarantine cannot run safely (vault location, unrecovered journal)."""


class OperationState(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ItemState(StrEnum):
    PENDING = "pending"
    QUARANTINED = "quarantined"
    ROLLED_BACK = "rolled_back"
    LOST = "lost"


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
class RecoveryReport:
    quarantined: tuple[Path, ...] = ()
    rolled_back: tuple[Path, ...] = ()
    lost: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()  # one per lost item; must be shown to the user


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
    ) -> None:
        self._preflight = Preflight(policy, open_files)
        data_dir = Path(policy.app_data_dir)
        for root in policy.default_roots():
            if data_dir.is_relative_to(root):
                raise QuarantineError(f"data directory {data_dir} is inside scan zone {root}")
        match = classifier.classify(data_dir / "quarantine" / "0" / "0")
        if match is not None:
            raise QuarantineError(f"data directory {data_dir} matches junk rule {match.rule_id}")
        self._conn = conn
        self._move = move
        self._vault = vault or Vault(data_dir)
        self._vault.ensure()

    # --- quarantine ----------------------------------------------------------------------------

    def quarantine(self, candidates: Sequence[Candidate]) -> QuarantineResult:
        if self._has_pending():
            raise QuarantineError("the journal has unfinished operations; run recover() first")
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
        for candidate in candidates:
            result = self._preflight.check(candidate)
            if isinstance(result, Refused):
                refused.append(result)
            elif result.stat.st_dev != device:
                refused.append(Refused(candidate.entry.path, RefusalReason.CROSS_DEVICE))
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
                    " mode, digest, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        operation_id,
                        str(original),
                        f"pending:{operation_id}:{index}",
                        entry.stat.st_size,
                        entry.stat.st_mtime_ns,
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
        """Move files back, newest first. Returns the items that had to stay in the vault."""
        kept: list[Moved] = []
        for item in reversed(moved):
            if self._move_back(item):
                self._set_item(item.item_id, ItemState.ROLLED_BACK)
            else:
                kept.append(item)
        moved_ids = {item.item_id for item in moved}
        for item in items:
            if item.item_id not in moved_ids:
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
        self._close_pending_operations()
        return RecoveryReport(
            quarantined=tuple(found[ItemState.QUARANTINED]),
            rolled_back=tuple(found[ItemState.ROLLED_BACK]),
            lost=tuple(found[ItemState.LOST]),
            warnings=tuple(warnings),
        )

    def _close_pending_operations(self) -> None:
        operations = self._conn.execute(
            "SELECT id FROM operations WHERE state = ?", (OperationState.PENDING,)
        ).fetchall()
        for (operation_id,) in operations:
            states = {
                ItemState(state)
                for (state,) in self._conn.execute(
                    "SELECT state FROM items WHERE operation_id = ?", (operation_id,)
                )
            }
            if states <= {ItemState.QUARANTINED}:
                self._finish(operation_id, OperationState.DONE, None)
            elif states == {ItemState.ROLLED_BACK}:
                self._finish(operation_id, OperationState.ROLLED_BACK, "interrupted; recovered")
            else:
                self._finish(operation_id, OperationState.FAILED, "interrupted; recovered")

    # --- journal helpers -----------------------------------------------------------------------

    def _has_pending(self) -> bool:
        row = self._conn.execute(
            "SELECT EXISTS (SELECT 1 FROM operations WHERE state = ?)", (OperationState.PENDING,)
        ).fetchone()
        return bool(row[0])

    def _set_item(self, item_id: int, state: ItemState) -> None:
        with transaction(self._conn):
            self._conn.execute("UPDATE items SET state = ? WHERE id = ?", (state, item_id))

    def _finish(self, operation_id: int, state: OperationState, error: str | None) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE operations SET state = ?, finished_at_ns = ?, error = ? WHERE id = ?",
                (state, time.time_ns(), error, operation_id),
            )


class _Copy(Enum):
    MATCHES = "matches"
    CHANGED = "changed"
    MISSING = "missing"


def _probe(slot: Path, size: int, mtime_ns: int) -> _Copy:
    """Is the vault copy the file we journaled (regular, same size and mtime_ns)?"""
    try:
        info = slot.lstat()
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
