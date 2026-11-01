"""Reading the journal after the code under test has written it."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from safeclean.storage.db import connect

Row = tuple[object, ...]


def rows(conn: sqlite3.Connection, sql: str, *params: object) -> list[Row]:
    return conn.execute(sql, params).fetchall()


def query(data_dir: Path, sql: str, *params: object) -> list[Row]:
    """Read the CLI's journal in ``data_dir`` after the commands under test have run."""
    conn = connect(data_dir / "journal.db")
    try:
        return rows(conn, sql, *params)
    finally:
        conn.close()
