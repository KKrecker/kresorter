"""Unfinished work in the journal, by domain (decision 0011, items 62, 99, 125).

Each domain journals into a table of its own; a ``pending`` row there is its unfinished work.
Any of it blocks new work of every domain until ``safeclean recover`` has run: all write to one
journal and must not interleave halfway.
"""

from __future__ import annotations

import sqlite3
from enum import StrEnum


class Domain(StrEnum):
    """A domain of work, named as its command."""

    QUARANTINE = "quarantine"
    AUTOSTART = "autostart"


_PENDING = {
    Domain.QUARANTINE: "SELECT EXISTS (SELECT 1 FROM operations WHERE state = 'pending')",
    Domain.AUTOSTART: "SELECT EXISTS (SELECT 1 FROM autostart_changes WHERE state = 'pending')",
}


def pending_domains(conn: sqlite3.Connection) -> set[Domain]:
    """The domains whose journal has a ``pending`` row: the recoveries still owed."""
    return {domain for domain, sql in _PENDING.items() if conn.execute(sql).fetchone()[0]}


def has_pending(conn: sqlite3.Connection) -> bool:
    """Is any domain's work unfinished (item 62)?"""
    return bool(pending_domains(conn))
