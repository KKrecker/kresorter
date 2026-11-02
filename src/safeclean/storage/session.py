"""The journal session of whatever acts: the CLI's commands and the window (decision 0014,
item 11; 0009, 0011 item 62).

The data directory is checked before anything is created there, the single-instance lock is
taken, and the journal is opened in it; quarantine, organize and autostart changes share all
three. Why the session could not run, or how its body stopped, is a value, ``SessionFailed``:
the CLI writes its message, the window shows it in its words. An ``OSError`` of the body is
the body's own, never the data directory's (0011 item 112); a journal error in the middle of
the body leaves an end that cannot be trusted (item 114).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from safeclean.core.scanner import ScanContext
from safeclean.storage.data_dir import PRIVATE, DataDirError, check_data_dir
from safeclean.storage.db import StorageError, connect
from safeclean.storage.lock import InstanceLock, LockedError

__all__ = [
    "JOURNAL_NAME",
    "LOCK_NAME",
    "SessionFailed",
    "SessionFailure",
    "run_session",
]

JOURNAL_NAME = "journal.db"
LOCK_NAME = "safeclean.lock"

T = TypeVar("T")


class SessionFailure(StrEnum):
    DATA_DIR = "data_dir"  # the data directory is where it must not be (0009)
    LOCKED = "locked"  # another safeclean holds the lock
    DATA_DIR_OS = "data_dir_os"  # creating the data directory or taking the lock failed
    JOURNAL_OPEN = "journal_open"  # the journal cannot be opened
    STOPPED = "stopped"  # the body stopped on an OSError of its own
    JOURNAL_FAILED = "journal_failed"  # the journal failed in the middle of the body


@dataclass(frozen=True)
class SessionFailed:
    failure: SessionFailure
    detail: str


def run_session(
    context: ScanContext, body: Callable[[sqlite3.Connection, Path], T]
) -> T | SessionFailed:
    """``body(journal, data directory)``, inside the lock, or why it could not run."""
    try:
        data_dir = check_data_dir(context.policy, context.classifier)
    except DataDirError as error:
        return SessionFailed(SessionFailure.DATA_DIR, str(error))
    try:
        data_dir.mkdir(mode=PRIVATE, parents=True, exist_ok=True)
        with InstanceLock(data_dir / LOCK_NAME):
            return _open(data_dir, body)
    except LockedError as error:
        return SessionFailed(SessionFailure.LOCKED, str(error))
    except OSError as error:
        return SessionFailed(SessionFailure.DATA_DIR_OS, str(error))


def _open(data_dir: Path, body: Callable[[sqlite3.Connection, Path], T]) -> T | SessionFailed:
    try:
        conn = connect(data_dir / JOURNAL_NAME)
    except (OSError, sqlite3.Error, StorageError) as error:
        return SessionFailed(SessionFailure.JOURNAL_OPEN, str(error))
    try:
        return body(conn, data_dir)
    except OSError as error:  # the body's own: not the data directory (0011 item 112)
        return SessionFailed(SessionFailure.STOPPED, str(error))
    except sqlite3.Error as error:  # in the middle: its end cannot be trusted (item 114)
        return SessionFailed(SessionFailure.JOURNAL_FAILED, str(error))
    finally:
        conn.close()
