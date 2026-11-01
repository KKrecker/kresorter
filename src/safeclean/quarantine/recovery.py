"""Recovery of interrupted quarantine operations, apart from the service (decision 0004).

``recover()`` reconciles what a crash left behind: ``pending`` quarantine items, and
quarantined items of a ``pending`` restore or purge; then it closes their operations. A vault
copy that no longer matches the journaled size/``mtime_ns`` is not ours to restore or purge: it
becomes ``lost`` and is reported loudly.

It reads the journal and the disk and needs nothing else: no open-file check, no vault to make,
no policy (pre-step-5 audit, B7). ``QuarantineService.recover()`` runs it.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from safeclean.quarantine.journal import (
    Copy,
    ItemState,
    OperationState,
    exists,
    finish_operation,
    probe,
    set_item,
)
from safeclean.storage.journal import Clock


@dataclass(frozen=True)
class RecoveryReport:
    quarantined: tuple[Path, ...] = ()
    rolled_back: tuple[Path, ...] = ()
    restored: tuple[Path, ...] = ()
    purged: tuple[Path, ...] = ()
    lost: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()  # one per lost item; must be shown to the user


def recover(conn: sqlite3.Connection, *, now: Clock = time.time_ns) -> RecoveryReport:
    """Reconcile pending items with the disk, then close their operations."""
    found: dict[ItemState, list[Path]] = {state: [] for state in ItemState}
    warnings: list[str] = []
    pending = conn.execute(
        "SELECT id, original_path, vault_path, size, mtime_ns FROM items"
        " WHERE state = ? ORDER BY id",
        (ItemState.PENDING,),
    ).fetchall()
    for item_id, original_text, vault_text, size, mtime_ns in pending:
        original, slot = Path(original_text), Path(vault_text)
        copy = probe(slot, size, mtime_ns)
        if copy is Copy.MATCHES:
            state = ItemState.QUARANTINED
        elif copy is Copy.CHANGED:
            state = ItemState.LOST
            warnings.append(
                f"LOST: the vault copy of {original} changed after the move ({slot});"
                " it will not be restored or purged"
            )
        elif exists(original):
            state = ItemState.ROLLED_BACK
        else:
            state = ItemState.LOST
            warnings.append(f"LOST: {original} is neither at its path nor in the vault")
        set_item(conn, item_id, state)
        found[state].append(original)
    rolling_back = conn.execute(
        "SELECT items.id, original_path, vault_path, size, mtime_ns FROM items"
        " JOIN operations ON items.operation_id = operations.id"
        " WHERE operations.state = ? AND items.state = ? ORDER BY items.id",
        (OperationState.PENDING, ItemState.QUARANTINED),
    ).fetchall()
    for item_id, original_text, vault_text, size, mtime_ns in rolling_back:
        # Interrupted during rollback: the move back may have happened unrecorded.
        original, slot = Path(original_text), Path(vault_text)
        copy = probe(slot, size, mtime_ns)
        if copy is Copy.MATCHES:
            continue  # still in the vault: stays quarantined, not reported again
        if copy is Copy.MISSING and probe(original, size, mtime_ns) is Copy.MATCHES:
            state = ItemState.ROLLED_BACK
        else:
            state = ItemState.LOST
            warnings.append(f"LOST: {original} is neither at its path nor intact in the vault")
        set_item(conn, item_id, state)
        found[state].append(original)
    restoring = conn.execute(
        "SELECT items.id, original_path, vault_path, size, mtime_ns FROM items"
        " JOIN operations ON items.restore_operation_id = operations.id"
        " WHERE operations.state = ? AND items.state = ? ORDER BY items.id",
        (OperationState.PENDING, ItemState.QUARANTINED),
    ).fetchall()
    for item_id, original_text, vault_text, size, mtime_ns in restoring:
        original, slot = Path(original_text), Path(vault_text)
        copy = probe(slot, size, mtime_ns)
        if copy is Copy.MATCHES:
            state = ItemState.QUARANTINED  # the move never happened
        elif copy is Copy.MISSING and probe(original, size, mtime_ns) is Copy.MATCHES:
            state = ItemState.RESTORED  # moved, journal update lost
        else:
            state = ItemState.LOST
            warnings.append(f"LOST: {original} is neither back at its path nor intact in the vault")
        set_item(conn, item_id, state)
        found[state].append(original)
    purging = conn.execute(
        "SELECT items.id, original_path, vault_path, size, mtime_ns FROM items"
        " JOIN operations ON items.purge_operation_id = operations.id"
        " WHERE operations.state = ? AND items.state = ? ORDER BY items.id",
        (OperationState.PENDING, ItemState.QUARANTINED),
    ).fetchall()
    for item_id, original_text, vault_text, size, mtime_ns in purging:
        original, slot = Path(original_text), Path(vault_text)
        copy = probe(slot, size, mtime_ns)
        if copy is Copy.MATCHES:
            state = ItemState.QUARANTINED  # the delete never happened
        elif copy is Copy.MISSING:
            state = ItemState.PURGED  # deleted, journal update lost
        else:
            state = ItemState.LOST
            warnings.append(
                f"LOST: the vault copy of {original} changed during a purge ({slot});"
                " it was not deleted"
            )
        set_item(conn, item_id, state)
        found[state].append(original)
    _close_pending_operations(conn, now)
    return RecoveryReport(
        quarantined=tuple(found[ItemState.QUARANTINED]),
        rolled_back=tuple(found[ItemState.ROLLED_BACK]),
        restored=tuple(found[ItemState.RESTORED]),
        purged=tuple(found[ItemState.PURGED]),
        lost=tuple(found[ItemState.LOST]),
        warnings=tuple(warnings),
    )


def _close_pending_operations(conn: sqlite3.Connection, now: Clock) -> None:
    operations = conn.execute(
        "SELECT id, kind FROM operations WHERE state = ?", (OperationState.PENDING,)
    ).fetchall()
    for operation_id, kind in operations:
        column, done, undone = _OPERATION_ITEMS[kind]
        states = {
            ItemState(state)
            for (state,) in conn.execute(
                f"SELECT state FROM items WHERE {column} = ?", (operation_id,)
            )
        }
        if states <= {done}:
            state, error = OperationState.DONE, None
        elif states == {undone}:
            state, error = OperationState.ROLLED_BACK, "interrupted; recovered"
        else:
            state, error = OperationState.FAILED, "interrupted; recovered"
        finish_operation(conn, operation_id, state, error, now=now)


# Per operation kind: the items column linking to it, the item state when the operation
# completed, and the item state when it did not happen at all.
_OPERATION_ITEMS: dict[str, tuple[str, ItemState, ItemState]] = {
    "quarantine": ("operation_id", ItemState.QUARANTINED, ItemState.ROLLED_BACK),
    "restore": ("restore_operation_id", ItemState.RESTORED, ItemState.QUARANTINED),
    "purge": ("purge_operation_id", ItemState.PURGED, ItemState.QUARANTINED),
}
