"""The journal of autostart changes, ``autostart_changes``: shared by XDG and Run (item 81).

A change is journaled ``pending`` with the values before and after it, before anything is
written, and finished as ``done``, ``rolled_back`` or ``failed``. Refusals are results that
journal nothing (item 70). Moved out of ``autostart.changes`` (pre-step-5 audit, B2).
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from enum import StrEnum

from safeclean.autostart.models import Source
from safeclean.storage.journal import insert_row
from safeclean.storage.transactions import transaction


class ChangeState(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"  # something was left on disk; recover() reconciles it
    ROLLED_BACK = "rolled_back"


class ChangeRefusal(StrEnum):
    READ_ONLY = "read_only"  # a source step 4 does not write (item 9)
    CHANGED = "changed"  # not the entry in effect as it was listed
    ALREADY = "already"  # already disabled, or already enabled
    PENDING = "pending"  # unfinished work in the journal: recover() first
    OTHER_DEVICE = "other_device"  # the store cannot hold the original by a link
    TOO_LARGE = "too_large"  # the disabled copy would be skipped by the reader
    FOREIGN = "foreign"  # not disabled by safeclean: enabling would edit it (item 74)
    ORIGINAL_CHANGED = "original_changed"  # the original in the store is missing or changed


@dataclass(frozen=True)
class ChangeResult:
    change_id: int | None  # None when refused
    state: ChangeState | None
    refusal: ChangeRefusal | None = None
    detail: str = ""


@dataclass(frozen=True)
class ChangeRecovery:
    """What ``recover()`` found: the ids of the pending changes it closed, by their end."""

    done: tuple[int, ...] = ()
    rolled_back: tuple[int, ...] = ()
    failed: tuple[int, ...] = ()


@dataclass(frozen=True)
class Change:
    """One row of ``autostart_changes``, as journaled before the change is made."""

    action: str  # "disable" or "enable"
    source: Source
    entry: str  # as listed
    location: str  # what is written
    digest: str
    before: bytes | None  # None: nothing there
    after: bytes | None


def insert_change(conn: sqlite3.Connection, change: Change) -> int:
    """Journal ``change`` as ``pending``; the caller holds the transaction."""
    return insert_row(
        conn,
        "INSERT INTO autostart_changes (action, source, entry, location, digest,"
        " value_before, value_after, state, created_at_ns)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            change.action,
            change.source.value,
            change.entry,
            change.location,
            change.digest,
            change.before,
            change.after,
            ChangeState.PENDING.value,
            time.time_ns(),
        ),
    )


def finish_change(
    conn: sqlite3.Connection, change_id: int, state: ChangeState, error: str | None
) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE autostart_changes SET state = ?, finished_at_ns = ?, error = ? WHERE id = ?",
            (state.value, time.time_ns(), error, change_id),
        )


def refused(refusal: ChangeRefusal, detail: str) -> ChangeResult:
    return ChangeResult(None, None, refusal, detail)
