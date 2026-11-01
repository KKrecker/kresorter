"""The journal session shared by the commands that act (decisions 0009, 0011 item 62).

The data directory is checked before anything is created there, the single-instance lock is
taken, and the journal is opened in it; quarantine and autostart changes share all three.

Exit code 3: the data directory, the lock or the journal cannot be used safely, or the body
stopped on an ``OSError`` it did not handle; only the first two are named the data directory.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from safeclean.core.scanner import ScanContext
from safeclean.quarantine.service import QuarantineError, check_data_dir
from safeclean.quarantine.vault import PRIVATE
from safeclean.storage.db import StorageError, connect
from safeclean.storage.lock import InstanceLock, LockedError

JOURNAL_NAME = "journal.db"
LOCK_NAME = "safeclean.lock"
UNSAFE = 3

Body = Callable[[sqlite3.Connection, Path], int]  # (journal, data directory) -> exit code


def with_journal(context: ScanContext, err: TextIO, body: Body) -> int:
    try:
        data_dir = check_data_dir(context.policy, context.classifier)
    except QuarantineError as error:
        err.write(f"safeclean: {error}\n")
        return UNSAFE
    try:
        data_dir.mkdir(mode=PRIVATE, parents=True, exist_ok=True)
        with InstanceLock(data_dir / LOCK_NAME):
            return _open(data_dir, err, body)
    except LockedError as error:
        err.write(f"safeclean: {error}\n")
        return UNSAFE
    except OSError as error:
        err.write(f"safeclean: cannot use the data directory: {error}\n")
        return UNSAFE


def _open(data_dir: Path, err: TextIO, body: Body) -> int:
    try:
        conn = connect(data_dir / JOURNAL_NAME)
    except (OSError, sqlite3.Error, StorageError) as error:
        err.write(f"safeclean: cannot open the journal: {error}\n")
        return UNSAFE
    try:
        return body(conn, data_dir)
    except OSError as error:  # the body's own: not the data directory (item 112)
        err.write(f"safeclean: stopped: {error}\n")
        return UNSAFE
    finally:
        conn.close()
