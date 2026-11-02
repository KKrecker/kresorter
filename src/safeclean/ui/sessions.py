"""The window's sessions in the journal, run in a task's worker (decision 0014, items 11 and 21).

A quarantine session runs as the CLI's does: the data directory is checked, the lock taken and
the journal opened (``storage.session``); the quarantine's own unfinished work is recovered
first, and unfinished work of another domain refuses an action before anything is changed (a
listing goes on, as ``quarantine list``). Without a reliable open-file check there is no
session. Each one ends with the quarantined files as they are then. What could not run is a
value the page shows in its words (``problem``). No Qt is needed here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from safeclean.core.preflight import UnreliableCheckerError
from safeclean.core.scanner import ScanContext
from safeclean.quarantine.journal import QuarantinedItem, quarantined
from safeclean.quarantine.recovery import RecoveryReport
from safeclean.quarantine.service import QuarantineService
from safeclean.storage.pending import Domain, pending_domains
from safeclean.storage.session import Journal, SessionFailed, run_session
from safeclean.ui.i18n import Translator

__all__ = ["Done", "NoReliableCheck", "Unfinished", "in_quarantine", "problem"]

T = TypeVar("T")


@dataclass(frozen=True)
class Unfinished:
    """Other domains have unfinished work: Recover comes first."""

    domains: frozenset[Domain]


@dataclass(frozen=True)
class NoReliableCheck:
    """No reliable open-file check on this system."""


@dataclass(frozen=True)
class Done(Generic[T]):
    recovered: RecoveryReport  # the quarantine's own unfinished work, settled first
    result: T
    listed: tuple[QuarantinedItem, ...]  # the quarantine after ``result``


def in_quarantine(
    context: ScanContext, act: Callable[[QuarantineService], T], *, listing: bool = False
) -> Done[T] | Unfinished | NoReliableCheck | SessionFailed:
    """``act`` on the quarantine, inside the session, or why it did not run; a ``listing`` is
    not stopped by other domains' unfinished work."""

    def body(conn: Journal, data_dir: Path) -> Done[T] | Unfinished | NoReliableCheck:
        try:
            service = QuarantineService(
                conn,
                policy=context.policy,
                open_files=context.open_files,
                classifier=context.classifier,
            )
        except UnreliableCheckerError:
            return NoReliableCheck()
        recovered = service.recover()
        others = set() if listing else pending_domains(conn)
        if others:  # its own was recovered above (0011 item 127)
            return Unfinished(frozenset(others))
        result = act(service)
        return Done(recovered, result, quarantined(conn))

    return run_session(context, body)


def problem(
    translator: Translator,
    outcome: Unfinished | NoReliableCheck | SessionFailed,
    *,
    no_check: str = "session.no_check",
) -> str:
    """Why a session did not act, in the window's words; ``no_check`` the key of what a page
    says without a reliable open-file check."""
    if isinstance(outcome, Unfinished):
        domains = ", ".join(translator.label(d) for d in Domain if d in outcome.domains)
        return translator.text("session.unfinished", domains=domains)
    if isinstance(outcome, NoReliableCheck):
        return translator.text(no_check)
    failure = translator.label(outcome.failure)
    return translator.text("session.failed", failure=failure, detail=outcome.detail)
