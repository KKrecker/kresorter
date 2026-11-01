"""`safeclean autostart recover`, and the quarantine naming it: end-to-end (commit 12c2a).

Autostart changes share the journal, the data directory and the lock with the quarantine
(decision 0011, item 62), so ``autostart recover`` builds the scan context to find them, as
the quarantine does. It reconciles the autostart changes of this platform only (item 100).
While one is unfinished, quarantine commands that would act refuse with exit 3 and name
``safeclean autostart recover``; ``quarantine list`` still runs. Real temporary trees and a
fake registry.
"""

import errno
import os
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, FakeRegistry, make_policy
from safeclean.autostart.changes import AutostartStore, XdgChanges
from safeclean.autostart.registry import Hive, RegValue, ValueKind
from safeclean.autostart.run_keys import APPROVED, RUN
from safeclean.autostart.xdg import read_xdg
from safeclean.core.heuristics import JunkClassifier, default_rules
from safeclean.core.scanner import ScanContext
from safeclean.storage.db import connect
from safeclean.storage.lock import InstanceLock
from support.cli import autostart_context, run
from support.files import write
from support.journal import query

APP = b"[Desktop Entry]\nType=Application\nName=App\nExec=/usr/bin/app --tray\n"
DISABLE = b"\x03\x00\x00\x00" + (133_444_736_000_000_000).to_bytes(8, "little")
FLAG = rf"HKCU\{APPROVED}\Sync"


def interrupted_xdg_disable(tmp_path: Path, data_dir: Path) -> Path:
    """A user entry disabled for real, its row left pending as a crash before the end would."""
    user, system = tmp_path / "config" / "autostart", tmp_path / "etc" / "xdg" / "autostart"
    entry = write(user / "app.desktop", APP)
    data_dir.mkdir(parents=True)
    conn = connect(data_dir / "journal.db")
    try:
        changes = XdgChanges(conn, AutostartStore(data_dir), user, (system,))
        (item,) = read_xdg(user, (system,)).items
        changes.disable(item)
        conn.execute("UPDATE autostart_changes SET state = 'pending', finished_at_ns = NULL")
    finally:
        conn.close()
    return entry


def no_space(*args: object, **kwargs: object) -> None:
    raise OSError(errno.ENOSPC, "No space left on device")


def denied_rename(source: object, target: object, **kwargs: object) -> None:
    raise PermissionError(errno.EACCES, "Permission denied", str(source), None, str(target))


def failed_partial_stub(tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Change 1 failed on a double fault, leaving an empty stub over a system entry: the stub."""
    user, system = tmp_path / "config" / "autostart", tmp_path / "etc" / "xdg" / "autostart"
    write(system / "app.desktop", APP)
    data_dir.mkdir(parents=True)
    conn = connect(data_dir / "journal.db")
    try:
        changes = XdgChanges(conn, AutostartStore(data_dir), user, (system,))
        (item,) = read_xdg(user, (system,)).items
        monkeypatch.setattr(os, "write", no_space)
        monkeypatch.setattr(os, "rename", no_space)  # it cannot go to the store either
        changes.disable(item)
        monkeypatch.undo()
    finally:
        conn.close()
    return user / "app.desktop"


def pending_run_change(data_dir: Path) -> None:
    data_dir.mkdir(parents=True)
    conn = connect(data_dir / "journal.db")
    try:
        conn.execute(
            "INSERT INTO autostart_changes (action, source, entry, location, digest, value_after,"
            " state, created_at_ns) VALUES ('disable', 'run_key', ?, ?, ?, ?, 'pending', 1)",
            (rf"HKCU\{RUN}\Sync", FLAG, "0" * 32, DISABLE),
        )
    finally:
        conn.close()


# --- autostart recover ---------------------------------------------------------------------------


def test_nothing_to_recover(tmp_path: Path, scan: ScanContext, data_dir: Path) -> None:
    code, out, err = run(["autostart", "recover"], scan, autostart_context("linux", tmp_path))

    assert (code, out, err) == (0, "Nothing to recover.\n", "")
    assert (data_dir / "journal.db").exists()  # the shared journal, in the data directory
    assert not (data_dir / "autostart").exists()  # the store is made by the first change only


def test_an_interrupted_xdg_change_is_closed_by_the_disk(
    tmp_path: Path, scan: ScanContext, data_dir: Path
) -> None:
    interrupted_xdg_disable(tmp_path, data_dir)

    code, out, err = run(["autostart", "recover"], scan, autostart_context("linux", tmp_path))

    assert (code, out, err) == (0, "Recovered 1 interrupted autostart change:\n  [1] done\n", "")
    assert query(data_dir, "SELECT state FROM autostart_changes") == [("done",)]


def test_an_interrupted_run_change_is_closed_by_the_registry(
    tmp_path: Path, scan: ScanContext, data_dir: Path
) -> None:
    pending_run_change(data_dir)
    flag = RegValue("Sync", ValueKind.REG_BINARY, b"\x02" + bytes(11))  # never written
    registry = FakeRegistry({(Hive.HKCU, APPROVED): [flag]})

    code, out, _ = run(
        ["autostart", "recover"], scan, autostart_context("windows", tmp_path, registry)
    )

    assert (code, out) == (0, "Recovered 1 interrupted autostart change:\n  [1] failed\n")
    assert registry.writes == []


def test_a_system_with_nothing_writable_has_nothing_to_recover(
    tmp_path: Path, scan: ScanContext
) -> None:
    code, out, _ = run(["autostart", "recover"], scan, autostart_context("darwin", tmp_path))

    assert (code, out) == (0, "Nothing to recover.\n")


def test_an_entry_that_cannot_be_read_stops_with_the_reason(
    tmp_path: Path, scan: ScanContext, data_dir: Path
) -> None:
    entry = interrupted_xdg_disable(tmp_path, data_dir)
    entry.rename(tmp_path / "elsewhere")
    entry.mkdir()

    code, out, err = run(["autostart", "recover"], scan, autostart_context("linux", tmp_path))

    assert (code, out) == (3, "")
    assert err == (
        "safeclean: an unfinished autostart change cannot be checked: not a regular file;"
        " fix or move what is there, then run 'safeclean autostart recover' again\n"
    )
    assert query(data_dir, "SELECT state FROM autostart_changes") == [("pending",)]


@pytest.mark.parametrize(
    "command", [["recover"], ["disable", "0", "--yes"]], ids=["recover", "disable"]
)
def test_a_partial_stub_that_cannot_be_moved_stops_with_the_reason(
    tmp_path: Path,
    scan: ScanContext,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
) -> None:
    stub = failed_partial_stub(tmp_path, data_dir, monkeypatch)
    before = query(data_dir, "SELECT state, error FROM autostart_changes")
    monkeypatch.setattr(os, "rename", denied_rename)

    code, out, err = run(["autostart", *command], scan, autostart_context("linux", tmp_path))

    monkeypatch.undo()
    slot = data_dir / "autostart" / "1"
    assert (code, out) == (3, "")
    assert err == (
        "safeclean: an unfinished autostart change cannot be closed: [Errno 13] Permission"
        f" denied: '{stub}' -> '{slot}'; fix or move what is there, then run"
        " 'safeclean autostart recover' again\n"
    )
    assert query(data_dir, "SELECT state, error FROM autostart_changes") == before
    assert stub.read_bytes() == b""  # still in place, never deleted


def test_an_unsafe_data_directory_is_refused_before_anything_is_created(
    tmp_path: Path, zone: Path
) -> None:
    rules = [r for r in default_rules() if r.id != "posix-temp"]
    policy = make_policy(tmp_path, tmp_path / "system", default_roots=[zone], app_data_dir=zone)
    unsafe = ScanContext(policy, FakeOpenFiles(), JunkClassifier(rules, platform="linux"), True)

    code, _, err = run(["autostart", "recover"], unsafe, autostart_context("linux", tmp_path))

    assert code == 3
    assert "inside scan zone" in err
    assert list(zone.iterdir()) == []


def test_a_running_instance_locks_it_out(tmp_path: Path, scan: ScanContext, data_dir: Path) -> None:
    data_dir.mkdir(parents=True)
    with InstanceLock(data_dir / "safeclean.lock"):
        code, _, err = run(["autostart", "recover"], scan, autostart_context("linux", tmp_path))

    assert code == 3
    assert "safeclean:" in err
    assert not (data_dir / "journal.db").exists()


# --- the quarantine names the command that recovers the other domain -----------------------------


@pytest.mark.parametrize(
    "args",
    [["add", "a.bin"], ["restore", "1"], ["purge", "1", "--yes"]],
    ids=["add", "restore", "purge"],
)
def test_quarantine_actions_wait_for_autostart_recover(
    tmp_path: Path, scan: ScanContext, data_dir: Path, zone: Path, args: list[str]
) -> None:
    pending_run_change(data_dir)
    target = write(zone / "a.bin", b"payload")
    args = [str(target) if a == "a.bin" else a for a in args]

    code, out, err = run(["quarantine", *args], scan, autostart_context("linux", tmp_path))

    assert (code, out) == (3, "")
    assert err == (
        "safeclean: an autostart change is unfinished; run 'safeclean autostart recover'"
        " first; nothing was changed\n"
    )
    assert target.read_bytes() == b"payload"
    assert query(data_dir, "SELECT COUNT(*) FROM operations") == [(0,)]


def test_quarantine_list_still_runs(tmp_path: Path, scan: ScanContext, data_dir: Path) -> None:
    pending_run_change(data_dir)

    code, out, _ = run(["quarantine", "list"], scan, autostart_context("linux", tmp_path))

    assert (code, out) == (0, "Quarantine: 0 files, 0 B\n")
