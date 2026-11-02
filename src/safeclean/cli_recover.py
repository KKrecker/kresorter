"""``safeclean recover``, and its alias ``safeclean autostart recover`` (decision 0011, item 126).

It opens the shared journal (data directory, lock) and reconciles the interrupted work of every
domain with the system: the quarantine's first, which needs no open-file check (item 124), then
organize's moves, which move nothing (decision 0012, items 31, 32), then the autostart changes
of this platform. It prints ``Nothing to recover.`` when there was none.
Each domain's own messages still name its own command (``autostart recover`` is this one).

Exit codes: 0 everything unfinished was closed, or nothing was; 2 usage error (argparse);
3 an unfinished autostart change that cannot be checked or closed (the quarantine's is closed
first), or a data directory, lock or journal that cannot be used.
"""

from __future__ import annotations

import argparse
import functools
import sqlite3
from pathlib import Path
from typing import TextIO

from safeclean import cli_autostart, cli_organize, cli_quarantine
from safeclean.autostart.changers import changes_for
from safeclean.autostart.listing import AutostartContext
from safeclean.cli_journal import RECOVER, UNSAFE, with_journal
from safeclean.core.scanner import ScanContext
from safeclean.organize import recovery as organize_recovery
from safeclean.quarantine import recovery


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    commands.add_parser("recover", help="reconcile interrupted work with the system")


def run(context: AutostartContext, scan: ScanContext, out: TextIO, err: TextIO) -> int:
    session = functools.partial(_recover, context, out, err)
    return with_journal(scan, err, session, recover=RECOVER)


def _recover(
    context: AutostartContext, out: TextIO, err: TextIO, conn: sqlite3.Connection, data_dir: Path
) -> int:
    found = cli_quarantine.report_recovery(recovery.recover(conn), out, err)
    found = cli_organize.report_recovery(organize_recovery.recover(conn), out, err) or found
    changes = changes_for(context, conn, data_dir)
    report = cli_autostart.recovered(changes, err)
    if report is None:
        return UNSAFE
    closed = cli_autostart.render_recovery(report)
    out.write(closed if closed or found else "Nothing to recover.\n")
    return 0
