"""The journal session of the commands that act, as the console reports it (decisions 0009,
0011 item 62). The session itself, shared with the window, is ``storage.session`` (0014 item
11): the data directory checked before anything is created there, the single-instance lock,
the journal opened in it.

Exit code 3: the data directory, the lock or the journal cannot be used safely, the body
stopped on an ``OSError`` it did not handle (only the first two are named the data directory),
or the journal failed in the middle of the command: then the domain's ``recover`` command, given
by it, is named (decision 0011, item 114). Work of another domain left in the journal is named
with ``safeclean recover``, the one command that recovers every domain (item 127).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from safeclean.core.scanner import ScanContext
from safeclean.storage.pending import Domain
from safeclean.storage.session import (
    JOURNAL_NAME,
    LOCK_NAME,
    SessionFailed,
    SessionFailure,
    run_session,
)

__all__ = ["JOURNAL_NAME", "LOCK_NAME", "RECOVER", "UNSAFE", "unfinished", "with_journal"]

UNSAFE = 3
RECOVER = "safeclean recover"

Body = Callable[[sqlite3.Connection, Path], int]  # (journal, data directory) -> exit code

_MESSAGES = {
    SessionFailure.DATA_DIR: "safeclean: {detail}\n",
    SessionFailure.LOCKED: "safeclean: {detail}\n",
    SessionFailure.DATA_DIR_OS: "safeclean: cannot use the data directory: {detail}\n",
    SessionFailure.JOURNAL_OPEN: "safeclean: cannot open the journal: {detail}\n",
    SessionFailure.STOPPED: "safeclean: stopped: {detail}\n",
    SessionFailure.JOURNAL_FAILED: "safeclean: journal failed: {detail}; run '{recover}'\n",
}


def with_journal(context: ScanContext, err: TextIO, body: Body, *, recover: str) -> int:
    """``body``'s exit code; 3, with the message on ``err``, when the session could not run
    (``storage.session``, decision 0014 item 11)."""
    result = run_session(context, body)
    if isinstance(result, SessionFailed):
        err.write(_MESSAGES[result.failure].format(detail=result.detail, recover=recover))
        return UNSAFE
    return result


def unfinished(domains: set[Domain]) -> str:
    """The refusal of a command that would act while other domains have unfinished work."""
    work = " and ".join(sorted(domains))
    return (
        f"safeclean: the journal has unfinished {work} work; run '{RECOVER}' first;"
        " nothing was changed\n"
    )
