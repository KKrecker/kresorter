"""`safeclean recover`, its alias `safeclean autostart recover`, and the commands naming it:
end-to-end (commit 12c2a; decision 0011, items 125-127; decision 0012, items 31, 32).

Autostart changes share the journal, the data directory and the lock with the quarantine
(item 62), so recovery builds the scan context to find them. One command closes the
interrupted work of every domain: the quarantine's first, which needs no open-file check
(item 124), then organize's moves, then the autostart changes of this platform. While work of
another domain is unfinished, a command that would act refuses with exit 3 and names
``safeclean recover``; ``quarantine list`` still runs. Real temporary trees and a fake registry.
"""

import errno
import os
from contextlib import closing
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, FakeRegistry, journal_held, make_policy
from safeclean.autostart.changes import AutostartStore, XdgChanges
from safeclean.autostart.registry import Hive, RegValue, ValueKind
from safeclean.autostart.run_keys import APPROVED, RUN
from safeclean.autostart.xdg import read_xdg
from safeclean.core.heuristics import JunkClassifier, default_rules
from safeclean.core.open_files import NoOpenFileCheck
from safeclean.core.scanner import ScanContext
from safeclean.organize.mover import carry_out
from safeclean.organize.undo import plan_undo
from safeclean.storage.db import connect
from safeclean.storage.lock import InstanceLock
from support.cli import autostart_context, run, scan_context
from support.files import write
from support.journal import query
from support.moves import MOVED, A, B, C, Fault, crash, planned, three_files

APP = b"[Desktop Entry]\nType=Application\nName=App\nExec=/usr/bin/app --tray\n"
DISABLE = b"\x03\x00\x00\x00" + (133_444_736_000_000_000).to_bytes(8, "little")
FLAG = rf"HKCU\{APPROVED}\Sync"
RECOVER = pytest.mark.parametrize(
    "command", [["recover"], ["autostart", "recover"]], ids=["recover", "alias"]
)


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


def crashed_undo(zone: Path, data_dir: Path, faults: dict[str, Fault]) -> Path:
    """Batch 1 sorted ``three_files``; its undo, batch 2, crashed where ``faults`` say."""
    data_dir.mkdir(parents=True, exist_ok=True)
    folder = three_files(zone)
    with closing(connect(data_dir / "journal.db")) as conn:
        carry_out(conn, folder, planned(folder))
        undo = plan_undo(conn, 1)
    moves = [(move.source, move.destination) for move in undo.moves]
    at = {folder / MOVED[name]: fault for name, fault in faults.items()}
    crash(data_dir / "journal.db", folder, moves, at, [move.undoes for move in undo.moves])
    return folder


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


# --- every domain ---------------------------------------------------------------------------------


@RECOVER
def test_nothing_to_recover(
    tmp_path: Path, scan: ScanContext, data_dir: Path, command: list[str]
) -> None:
    code, out, err = run(command, scan, autostart_context("linux", tmp_path))

    assert (code, out, err) == (0, "Nothing to recover.\n", "")
    assert (data_dir / "journal.db").exists()  # the shared journal, in the data directory
    assert not (data_dir / "autostart").exists()  # the store is made by the first change only
    assert not (data_dir / "quarantine").exists()  # the vault, by the first quarantine only


@RECOVER
def test_every_domain_is_recovered_the_quarantine_first(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path, command: list[str]
) -> None:
    quarantined(scan, zone)
    interrupted_xdg_disable(tmp_path, data_dir)
    left_pending(data_dir)

    code, out, err = run(command, scan, autostart_context("linux", tmp_path))

    assert (code, err) == (0, "")
    assert out == (
        "Recovered an interrupted quarantine operation (1 file).\n"
        "Recovered 1 interrupted autostart change:\n  [1] done\n"
    )
    assert query(data_dir, "SELECT state FROM operations") == [("done",)]
    assert query(data_dir, "SELECT state FROM items") == [("quarantined",)]
    assert query(data_dir, "SELECT state FROM autostart_changes") == [("done",)]


def test_the_moves_are_recovered_after_the_quarantine_and_before_autostart(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.32]
    quarantined(scan, zone)
    interrupted_xdg_disable(tmp_path, data_dir)
    left_pending(data_dir)
    crashed_batch(zone, data_dir, {A: "exit-before"})

    code, out, err = run(["recover"], scan, autostart_context("linux", tmp_path))

    assert (code, err) == (0, "")
    assert out == (
        "Recovered an interrupted quarantine operation (1 file).\n"
        "Recovered 1 interrupted organize batch:\n  [1] rolled_back\n"
        "Recovered 1 interrupted autostart change:\n  [1] done\n"
    )


@RECOVER
def test_an_interrupted_organize_batch_names_the_files_still_sorted(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path, command: list[str]
) -> None:
    # [0012.31] recovery completes nothing and rolls nothing back: undo is the user's choice
    folder = crashed_batch(zone, data_dir, {B: "exit-after"})

    code, out, err = run(command, scan, autostart_context("linux", tmp_path))

    assert (code, err) == (0, "")
    assert out == (
        "Recovered 1 interrupted organize batch:\n"
        "  [1] failed: 2 files still sorted; 'safeclean organize undo 1' moves them back\n"
        f"    {folder / MOVED[A]}\n"
        f"    {folder / MOVED[B]}\n"
    )
    assert query(data_dir, "SELECT state FROM moves ORDER BY id") == [
        ("done",),
        ("done",),
        ("rolled_back",),
    ]
    assert query(data_dir, "SELECT state FROM move_batches") == [("failed",)]


def test_one_file_still_sorted_is_named_alone(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.31]
    folder = crashed_batch(zone, data_dir, {A: "exit-after"})

    code, out, _ = run(["recover"], scan, autostart_context("linux", tmp_path))

    assert (code, out) == (
        0,
        "Recovered 1 interrupted organize batch:\n"
        "  [1] failed: 1 file still sorted; 'safeclean organize undo 1' moves it back\n"
        f"    {folder / MOVED[A]}\n",
    )


def test_two_interrupted_batches_are_counted(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.31] oldest first, each with its own line
    folder = crashed_batch(zone, data_dir, {A: "exit-after"})
    desktop = zone / "Desktop"
    write(desktop / "d.jpg")
    moves = [(desktop / "d.jpg", desktop / "Images" / "d.jpg")]
    crash(data_dir / "journal.db", desktop, moves, {desktop / "d.jpg": "exit-before"})

    code, out, _ = run(["recover"], scan, autostart_context("linux", tmp_path))

    assert (code, out) == (
        0,
        "Recovered 2 interrupted organize batches:\n"
        "  [1] failed: 1 file still sorted; 'safeclean organize undo 1' moves it back\n"
        f"    {folder / MOVED[A]}\n"
        "  [2] rolled_back\n",
    )


def test_a_move_recovery_cannot_settle_is_warned_about_on_stderr(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.31] the file at both paths: neither is touched, the user decides
    folder = crashed_batch(zone, data_dir, {A: "exit-after"})
    (folder / A).hardlink_to(folder / MOVED[A])

    code, out, err = run(["recover"], scan, autostart_context("linux", tmp_path))

    assert (code, out) == (0, "Recovered 1 interrupted organize batch:\n  [1] failed\n")
    assert err == (
        f"safeclean: FAILED: {folder / A} -> {folder / MOVED[A]}: at the source the file,"
        " at the destination the file; neither was touched\n"
    )
    assert (folder / A).read_bytes() == (folder / MOVED[A]).read_bytes() == A.encode()


@pytest.mark.parametrize(
    ("faults", "state"),
    [({B: "exit-after"}, "failed"), ({A: "exit-before"}, "rolled_back")],
    ids=["failed", "rolled-back"],
)
def test_an_interrupted_undo_names_the_batch_it_undoes(
    tmp_path: Path,
    scan: ScanContext,
    zone: Path,
    data_dir: Path,
    faults: dict[str, Fault],
    state: str,
) -> None:
    # [0012.29] [0012.31] an undo cannot be undone: undoing its batch again takes the rest
    crashed_undo(zone, data_dir, faults)

    code, out, err = run(["recover"], scan, autostart_context("linux", tmp_path))

    assert (code, err) == (0, "")
    assert out == (
        "Recovered 1 interrupted organize batch:\n"
        f"  [2] {state}: the undo of batch 1 stopped;"
        " 'safeclean organize undo 1' moves back the files still sorted\n"
    )


def test_an_interrupted_undo_that_finished_is_done(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.31] the crash came after the last move back
    crashed_undo(zone, data_dir, {C: "exit-after"})

    code, out, _ = run(["recover"], scan, autostart_context("linux", tmp_path))

    assert (code, out) == (0, "Recovered 1 interrupted organize batch:\n  [2] done\n")


def test_the_moves_are_recovered_where_organize_does_not_move(
    tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.37] recovery moves nothing, so it runs everywhere
    crashed_batch(zone, data_dir, {C: "exit-before"})
    unchecked = scan_context(tmp_path, zone, data_dir, NoOpenFileCheck())

    code, out, err = run(["recover"], unchecked, autostart_context("windows", tmp_path))

    assert (code, err) == (0, "")
    assert out.startswith("Recovered 1 interrupted organize batch:\n  [1] failed: 2 files")


@RECOVER
def test_the_quarantine_is_recovered_without_an_open_file_check(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path, command: list[str]
) -> None:
    """Where the quarantine refuses to act (macOS, Windows), its work is still closed (B7)."""
    quarantined(scan, zone)
    left_pending(data_dir)
    unchecked = scan_context(tmp_path, zone, data_dir, NoOpenFileCheck())

    code, out, err = run(command, unchecked, autostart_context("darwin", tmp_path))

    assert (code, out, err) == (0, "Recovered an interrupted quarantine operation (1 file).\n", "")
    assert query(data_dir, "SELECT state FROM operations") == [("done",)]
    assert query(data_dir, "SELECT state FROM items") == [("quarantined",)]


def test_a_lost_file_is_warned_about_on_stderr(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    path = quarantined(scan, zone)
    left_pending(data_dir)
    copy = data_dir / "quarantine" / "1" / "1"
    copy.write_bytes(b"tampered")

    code, out, err = run(["recover"], scan, autostart_context("linux", tmp_path))

    assert (code, out) == (0, "Recovered an interrupted quarantine operation (1 file).\n")
    assert err == (
        f"safeclean: LOST: the vault copy of {path} changed after the move ({copy});"
        " it will not be restored or purged\n"
    )
    assert query(data_dir, "SELECT state FROM items") == [("lost",)]


def test_an_autostart_change_that_cannot_be_checked_leaves_the_quarantine_recovered(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    quarantined(scan, zone)
    entry = interrupted_xdg_disable(tmp_path, data_dir)
    left_pending(data_dir)
    entry.rename(tmp_path / "elsewhere")
    entry.mkdir()

    code, out, err = run(["recover"], scan, autostart_context("linux", tmp_path))

    assert (code, out) == (3, "Recovered an interrupted quarantine operation (1 file).\n")
    assert err == (
        "safeclean: an unfinished autostart change cannot be checked: not a regular file;"
        " fix or move what is there, then run 'safeclean autostart recover' again\n"
    )
    assert query(data_dir, "SELECT state FROM operations") == [("done",)]
    assert query(data_dir, "SELECT state FROM autostart_changes") == [("pending",)]


@RECOVER
def test_a_journal_failure_names_safeclean_recover(
    tmp_path: Path,
    scan: ScanContext,
    zone: Path,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
) -> None:
    quarantined(scan, zone)
    left_pending(data_dir)

    with journal_held(monkeypatch, data_dir):
        code, out, err = run(command, scan, autostart_context("linux", tmp_path))

    assert (code, out) == (3, "")
    assert err == "safeclean: journal failed: database is locked; run 'safeclean recover'\n"
    assert query(data_dir, "SELECT state FROM operations") == [("pending",)]


# --- autostart changes ---------------------------------------------------------------------------


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
    classifier = JunkClassifier(rules, platform="linux")
    unsafe = ScanContext(policy, FakeOpenFiles(), classifier, True, "linux")

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


# --- a command of another domain names it --------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [["add", "a.bin"], ["restore", "1"], ["purge", "1", "--yes"]],
    ids=["add", "restore", "purge"],
)
def test_quarantine_actions_wait_for_safeclean_recover(
    tmp_path: Path, scan: ScanContext, data_dir: Path, zone: Path, args: list[str]
) -> None:
    pending_run_change(data_dir)
    target = write(zone / "a.bin", b"payload")
    args = [str(target) if a == "a.bin" else a for a in args]

    code, out, err = run(["quarantine", *args], scan, autostart_context("linux", tmp_path))

    assert (code, out) == (3, "")
    assert err == (
        "safeclean: the journal has unfinished autostart work; run 'safeclean recover' first;"
        " nothing was changed\n"
    )
    assert target.read_bytes() == b"payload"
    assert query(data_dir, "SELECT COUNT(*) FROM operations") == [(0,)]


def pending_move_batch(data_dir: Path) -> None:
    """An organize batch a crash left pending."""
    data_dir.mkdir(parents=True)
    conn = connect(data_dir / "journal.db")
    try:
        conn.execute(
            "INSERT INTO move_batches (kind, folder, state, created_at_ns)"
            " VALUES ('organize', '/home/a/Downloads', 'pending', 1)"
        )
    finally:
        conn.close()


@pytest.mark.parametrize(
    "args",
    [["add", "a.bin"], ["restore", "1"], ["purge", "1", "--yes"]],
    ids=["add", "restore", "purge"],
)
def test_quarantine_actions_wait_for_an_unfinished_organize_batch(
    tmp_path: Path, scan: ScanContext, data_dir: Path, zone: Path, args: list[str]
) -> None:
    # [0012.32]
    pending_move_batch(data_dir)
    target = write(zone / "a.bin", b"payload")
    args = [str(target) if a == "a.bin" else a for a in args]

    code, out, err = run(["quarantine", *args], scan, autostart_context("linux", tmp_path))

    assert (code, out) == (3, "")
    assert err == (
        "safeclean: the journal has unfinished organize work; run 'safeclean recover' first;"
        " nothing was changed\n"
    )
    assert target.read_bytes() == b"payload"
    assert query(data_dir, "SELECT COUNT(*) FROM operations") == [(0,)]


def test_quarantine_list_still_runs(tmp_path: Path, scan: ScanContext, data_dir: Path) -> None:
    pending_run_change(data_dir)

    code, out, _ = run(["quarantine", "list"], scan, autostart_context("linux", tmp_path))

    assert (code, out) == (0, "Quarantine: 0 files, 0 B\n")
