"""Unfinished work in the journal, in either domain (decision 0011, items 62, 99).

A pending quarantine operation and a pending autostart change both block new work of either
kind until the ``recover()`` of their own domain has run: both write to one journal and must
not interleave halfway.
"""

from __future__ import annotations

import sqlite3


def has_pending(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM operations WHERE state = 'pending')"
        " OR EXISTS (SELECT 1 FROM autostart_changes WHERE state = 'pending')"
    ).fetchone()
    return bool(row[0])
