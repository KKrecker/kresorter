"""Work a crash left unfinished, in each domain, as ``safeclean recover`` finds it: a quarantine
operation, an organize batch, an autostart change (decision 0011, item 126; 0012, item 32)."""

from __future__ import annotations

from pathlib import Path

from safeclean.autostart.changes import AutostartStore, XdgChanges
from safeclean.autostart.xdg import read_xdg
from safeclean.core.scanner import ScanContext
from safeclean.storage.db import connect
from support.cli import run
from support.files import write
from support.journal import query
from support.moves import Fault, crash, planned, three_files

APP = b"[Desktop Entry]\nType=Application\nName=App\nExec=/usr/bin/app --tray\n"


def interrupted_xdg_disable(tmp_path: Path, data_dir: Path) -> Path:
    """A user entry disabled for real, its row left pending as a crash before the end would."""
    user, system = tmp_path / "config" / "autostart", tmp_path / "etc" / "xdg" / "autostart"
    entry = write(user / "app.desktop", APP)
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(data_dir / "journal.db")
    try:
        changes = XdgChanges(conn, AutostartStore(data_dir), user, (system,))
        (item,) = read_xdg(user, (system,)).items
        changes.disable(item)
        conn.execute("UPDATE autostart_changes SET state = 'pending', finished_at_ns = NULL")
    finally:
        conn.close()
    return entry


def quarantined(scan: ScanContext, zone: Path) -> Path:
    """A file moved into the quarantine for real; the operation is done."""
    path = write(zone / "a.bin")
    assert run(["quarantine", "add", str(path)], scan)[0] == 0
    return path


def left_pending(data_dir: Path) -> None:
    """The quarantine's operation as a crash right after the move would leave it."""
    query(data_dir, "UPDATE items SET state = 'pending'")
    query(data_dir, "UPDATE operations SET state = 'pending', finished_at_ns = NULL")


def crashed_batch(zone: Path, data_dir: Path, faults: dict[str, Fault]) -> Path:
    """An organize batch of ``three_files`` that crashed where ``faults`` say: its folder."""
    data_dir.mkdir(parents=True, exist_ok=True)
    folder = three_files(zone)
    at = {folder / name: fault for name, fault in faults.items()}
    crash(data_dir / "journal.db", folder, planned(folder), at)
    return folder
