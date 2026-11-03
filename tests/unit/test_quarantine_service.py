"""Quarantine service and vault (decision 0004, items 1, 3, 4; vault location section).

Moves go through an injectable ``move`` (default ``Path.rename``) so failures and crashes can be
simulated without touching real devices. ``recover()`` cases build journal and disk states
directly, as a crash would leave them.
"""

import functools
import itertools
import os
import sqlite3
import stat
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy, windows_rename
from kresorter.core.hashing import hash_file
from kresorter.core.heuristics import JunkClassifier, load_rules
from kresorter.core.models import FileEntry
from kresorter.core.open_files import NoOpenFileCheck
from kresorter.core.policy import PathPolicy
from kresorter.core.preflight import Candidate, RefusalReason, UnreliableCheckerError
from kresorter.quarantine.journal import OperationState
from kresorter.quarantine.recovery import RecoveryReport
from kresorter.quarantine.service import QuarantineError, QuarantineService
from kresorter.quarantine.vault import Vault
from kresorter.storage.db import connect
from support.files import write
from support.host import MTIME_STEP_NS, as_kept
from support.journal import rows

NO_RULES = JunkClassifier([], platform="linux")

# --- helpers -----------------------------------------------------------------------------------


def scanned(path: Path) -> FileEntry:
    info = path.lstat()
    return FileEntry(path=path, size=info.st_size, mtime_ns=info.st_mtime_ns)


def mode_bits(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


Move = Callable[[Path, Path], object]


def failing_on(call: int, error: BaseException, before: Callable[[], None] = lambda: None) -> Move:
    """``Path.rename`` that raises ``error`` on the ``call``-th call (1-based)."""
    calls = 0

    def move(source: Path, target: Path) -> object:
        nonlocal calls
        calls += 1
        if calls == call:
            before()
            raise error
        return source.rename(target)

    return move


@pytest.fixture
def policy(tmp_path: Path, zone: Path, data_dir: Path) -> PathPolicy:
    return make_policy(tmp_path, tmp_path / "system", default_roots=[zone], app_data_dir=data_dir)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    (tmp_path / "journal").mkdir()
    connection = connect(tmp_path / "journal" / "journal.db")
    yield connection
    connection.close()


def make_service(
    conn: sqlite3.Connection,
    policy: PathPolicy,
    *,
    move: Move = Path.rename,
    vault: Vault | None = None,
) -> QuarantineService:
    return QuarantineService(
        conn,
        policy=policy,
        open_files=FakeOpenFiles(),
        classifier=NO_RULES,
        move=move,
        vault=vault,
    )


@pytest.fixture
def service(conn: sqlite3.Connection, policy: PathPolicy) -> QuarantineService:
    return make_service(conn, policy)


# --- construction: refuse to start -------------------------------------------------------------


def test_unreliable_checker_is_refused(conn: sqlite3.Connection, policy: PathPolicy) -> None:
    with pytest.raises(UnreliableCheckerError):
        QuarantineService(conn, policy=policy, open_files=NoOpenFileCheck(), classifier=NO_RULES)


def test_data_dir_inside_a_default_root_is_refused(
    conn: sqlite3.Connection, tmp_path: Path, zone: Path
) -> None:
    policy = make_policy(tmp_path, default_roots=[zone], app_data_dir=zone / "xdg" / "kresorter")
    with pytest.raises(QuarantineError, match="scan zone"):
        make_service(conn, policy)


def test_data_dir_matching_a_junk_rule_is_refused(
    conn: sqlite3.Connection, tmp_path: Path, zone: Path
) -> None:
    rules = load_rules(
        '[[rule]]\nid = "junkdir"\ncategory = "cache"\ndescription = "x"\ndirs = ["junkdir"]\n'
    )
    policy = make_policy(tmp_path, default_roots=[zone], app_data_dir=tmp_path / "junkdir" / "sc")
    with pytest.raises(QuarantineError, match="junkdir"):
        QuarantineService(
            conn,
            policy=policy,
            open_files=FakeOpenFiles(),
            classifier=JunkClassifier(rules, platform="linux"),
        )


# --- vault -------------------------------------------------------------------------------------


def test_vault_is_created_private(service: QuarantineService, data_dir: Path) -> None:
    assert mode_bits(data_dir) == as_kept(0o700, directory=True)
    assert mode_bits(data_dir / "quarantine") == as_kept(0o700, directory=True)


def test_existing_loose_vault_is_tightened(
    conn: sqlite3.Connection, policy: PathPolicy, data_dir: Path
) -> None:
    (data_dir / "quarantine").mkdir(parents=True)
    data_dir.chmod(0o755)
    (data_dir / "quarantine").chmod(0o777)
    make_service(conn, policy)
    assert mode_bits(data_dir) == as_kept(0o700, directory=True)
    assert mode_bits(data_dir / "quarantine") == as_kept(0o700, directory=True)


def test_vault_slot_layout(data_dir: Path) -> None:
    assert Vault(data_dir).slot(7, 42) == data_dir / "quarantine" / "7" / "42"


# --- quarantine: happy path --------------------------------------------------------------------


def test_files_are_moved_into_the_vault_and_journaled(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path, data_dir: Path
) -> None:
    a = scanned(write(zone / "a.bin", b"aaa"))
    b = scanned(write(zone / "b.bin", b"bbbb"))
    modes = (a.path.lstat().st_mode, b.path.lstat().st_mode)

    result = service.quarantine([Candidate(entry=a), Candidate(entry=b)])

    assert result.state is OperationState.DONE
    assert result.refused == ()
    assert [m.original for m in result.moved] == [a.path, b.path]
    assert not a.path.exists()
    assert not b.path.exists()
    first = result.moved[0]
    expected_slot = data_dir / "quarantine" / str(result.operation_id) / str(first.item_id)
    assert first.vault_path == expected_slot
    assert first.vault_path.read_bytes() == b"aaa"
    assert mode_bits(first.vault_path.parent) == 0o700
    assert rows(conn, "SELECT kind, state FROM operations") == [("quarantine", "done")]
    assert rows(conn, "SELECT finished_at_ns IS NOT NULL FROM operations") == [(1,)]
    assert rows(
        conn, "SELECT original_path, size, mtime_ns, mode, state FROM items ORDER BY id"
    ) == [
        (str(a.path), 3, a.mtime_ns, modes[0], "quarantined"),
        (str(b.path), 4, b.mtime_ns, modes[1], "quarantined"),
    ]


def test_journal_times_come_from_the_given_clock(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    clock = functools.partial(next, itertools.count(1))
    service = QuarantineService(
        conn, policy=policy, open_files=FakeOpenFiles(), classifier=NO_RULES, now=clock
    )
    (moved,) = service.quarantine([Candidate(entry=scanned(write(zone / "a.bin")))]).moved

    service.restore([moved.item_id])

    sql = "SELECT kind, created_at_ns, finished_at_ns FROM operations ORDER BY id"
    assert rows(conn, sql) == [("quarantine", 1, 2), ("restore", 3, 4)]  # item 121


def test_duplicate_digest_is_journaled(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    a = scanned(write(zone / "a.bin"))
    twin = scanned(write(zone / "b.bin"))
    digest = hash_file(twin.path)
    service.quarantine([Candidate(entry=a, twin=twin, digest=digest)])
    assert rows(conn, "SELECT digest FROM items") == [(digest,)]


def test_journal_is_written_before_the_move(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    seen: list[tuple[list[tuple[object, ...]], Path, bool]] = []

    def spy(source: Path, target: Path) -> object:
        journal = rows(conn, "SELECT original_path, vault_path, state FROM items")
        seen.append((journal, target, target.exists()))
        return source.replace(target)

    a = scanned(write(zone / "a.bin"))
    make_service(conn, policy, move=spy).quarantine([Candidate(entry=a)])

    assert len(seen) == 1
    journal, target, target_existed = seen[0]
    assert journal == [(str(a.path), str(target), "pending")]  # committed before the move
    assert target_existed is False


# --- quarantine: refusals ----------------------------------------------------------------------


def test_refused_candidates_are_reported_and_the_rest_proceeds(
    service: QuarantineService, zone: Path
) -> None:
    ok = scanned(write(zone / "ok.bin"))
    changed = scanned(write(zone / "changed.bin"))
    write(changed.path, b"different size")

    result = service.quarantine([Candidate(entry=ok), Candidate(entry=changed)])

    assert [m.original for m in result.moved] == [ok.path]
    assert [(r.path, r.reason) for r in result.refused] == [(changed.path, RefusalReason.CHANGED)]
    assert changed.path.read_bytes() == b"different size"


def test_same_file_twice_in_one_batch_is_refused_up_front(
    service: QuarantineService, zone: Path
) -> None:
    # Refused on input, not discovered later as an OSError that rolls back the whole batch.
    a = scanned(write(zone / "a.bin"))
    b = scanned(write(zone / "b.bin"))

    result = service.quarantine([Candidate(entry=a), Candidate(entry=b), Candidate(entry=a)])

    assert result.state is OperationState.DONE
    assert [m.original for m in result.moved] == [a.path, b.path]
    assert [(r.path, r.reason) for r in result.refused] == [
        (a.path, RefusalReason.DUPLICATE_CANDIDATE)
    ]


def test_all_refused_creates_no_operation(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    gone = FileEntry(path=zone / "gone.bin", size=1, mtime_ns=1)
    result = service.quarantine([Candidate(entry=gone)])
    assert result.operation_id is None
    assert result.state is None
    assert rows(conn, "SELECT COUNT(*) FROM operations") == [(0,)]


def test_file_on_another_device_is_refused(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path, data_dir: Path
) -> None:
    class OtherDevice(Vault):
        def device(self) -> int:
            return super().device() + 1

    a = scanned(write(zone / "a.bin"))
    service = make_service(conn, policy, vault=OtherDevice(data_dir))
    result = service.quarantine([Candidate(entry=a)])

    assert [(r.path, r.reason) for r in result.refused] == [(a.path, RefusalReason.CROSS_DEVICE)]
    assert a.path.exists()
    assert result.moved == ()


def test_unrecovered_journal_blocks_new_operations(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    conn.execute(
        "INSERT INTO operations (kind, state, created_at_ns) VALUES ('quarantine', 'pending', 1)"
    )
    with pytest.raises(QuarantineError, match="recover"):
        service.quarantine([Candidate(entry=scanned(write(zone / "a.bin")))])


def pending_autostart_change(conn: sqlite3.Connection) -> None:
    """An autostart change journaled but not finished (decision 0011, item 62)."""
    conn.execute(
        "INSERT INTO autostart_changes (action, source, entry, location, digest, value_after,"
        " state, created_at_ns) VALUES ('disable', 'xdg_autostart', '/e', '/l', ?, x'00',"
        " 'pending', 1)",
        ("0" * 32,),
    )


@pytest.mark.parametrize("call", ["quarantine", "restore", "plan_purge", "purge"])
def test_an_unfinished_autostart_change_blocks_every_operation(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path, call: str
) -> None:
    (moved,) = service.quarantine([Candidate(entry=scanned(write(zone / "a.bin")))]).moved
    plan = service.plan_purge([moved.item_id])  # planned before the change was journaled
    pending_autostart_change(conn)
    actions: dict[str, Callable[[], object]] = {
        "quarantine": lambda: service.quarantine([Candidate(entry=scanned(write(zone / "b.bin")))]),
        "restore": lambda: service.restore([moved.item_id]),
        "plan_purge": lambda: service.plan_purge([moved.item_id]),
        "purge": lambda: service.purge(plan),
    }
    journal = rows(conn, "SELECT id, state FROM operations")

    with pytest.raises(QuarantineError, match="recover"):
        actions[call]()

    assert rows(conn, "SELECT id, state FROM operations") == journal
    assert moved.vault_path.exists()


def test_recover_leaves_unfinished_autostart_changes_to_autostart(
    service: QuarantineService, conn: sqlite3.Connection
) -> None:
    pending_autostart_change(conn)

    service.recover()

    assert rows(conn, "SELECT state FROM autostart_changes") == [("pending",)]


# --- quarantine: atomic batch ------------------------------------------------------------------


def test_failure_mid_batch_moves_everything_back(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    a = scanned(write(zone / "a.bin", b"aaa"))
    b = scanned(write(zone / "b.bin", b"bbb"))
    service = make_service(conn, policy, move=failing_on(2, OSError(5, "I/O error")))

    result = service.quarantine([Candidate(entry=a), Candidate(entry=b)])

    assert result.state is OperationState.ROLLED_BACK
    assert "I/O error" in result.error
    assert result.moved == ()
    assert a.path.read_bytes() == b"aaa"
    assert b.path.read_bytes() == b"bbb"
    assert rows(conn, "SELECT state FROM operations") == [("rolled_back",)]
    assert rows(conn, "SELECT state FROM items") == [("rolled_back",), ("rolled_back",)]


def test_interrupt_mid_batch_rolls_back_then_propagates(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    a = scanned(write(zone / "a.bin"))
    b = scanned(write(zone / "b.bin"))
    service = make_service(conn, policy, move=failing_on(2, KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        service.quarantine([Candidate(entry=a), Candidate(entry=b)])

    assert a.path.exists()
    assert b.path.exists()
    assert rows(conn, "SELECT state FROM operations") == [("rolled_back",)]


def interrupted_after(call: int) -> Move:
    """``Path.replace`` whose ``call``-th rename completes, then an interrupt arrives."""
    calls = 0

    def move(source: Path, target: Path) -> object:
        nonlocal calls
        calls += 1
        source.replace(target)
        if calls == call:
            raise KeyboardInterrupt
        return None

    return move


def test_interrupt_right_after_a_completed_rename_still_rolls_it_back(
    conn: sqlite3.Connection, policy: PathPolicy, data_dir: Path, zone: Path
) -> None:
    # The rename happened but the service never learned it: the disk, not memory, decides.
    a = scanned(write(zone / "a.bin", b"aaa"))
    service = make_service(conn, policy, move=interrupted_after(1))

    with pytest.raises(KeyboardInterrupt):
        service.quarantine([Candidate(entry=a)])

    assert a.path.read_bytes() == b"aaa"
    assert not any(p.is_file() for p in (data_dir / "quarantine").rglob("*"))
    assert rows(conn, "SELECT state FROM items") == [("rolled_back",)]
    assert rows(conn, "SELECT state FROM operations") == [("rolled_back",)]


def test_interrupt_during_rollback_is_reconciled_from_disk_by_recover(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    # Move 1 (a) succeeds, move 2 (b) fails, move 3 puts a back and is then interrupted:
    # a is home again but the journal still says quarantined, and the operation is pending.
    a = scanned(write(zone / "a.bin", b"aaa"))
    b = scanned(write(zone / "b.bin", b"bbb"))
    calls = 0

    def move(source: Path, target: Path) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(5, "I/O error")
        source.replace(target)
        if calls == 3:
            raise KeyboardInterrupt
        return None

    service = make_service(conn, policy, move=move)
    with pytest.raises(KeyboardInterrupt):
        service.quarantine([Candidate(entry=a), Candidate(entry=b)])
    assert rows(conn, "SELECT state FROM operations") == [("pending",)]

    report = service.recover()

    assert set(report.rolled_back) == {a.path, b.path}
    assert report.lost == ()
    assert rows(conn, "SELECT state FROM items ORDER BY id") == [("rolled_back",), ("rolled_back",)]
    assert rows(conn, "SELECT state FROM operations") == [("rolled_back",)]
    assert a.path.read_bytes() == b"aaa"


def test_rollback_never_overwrites_a_new_file_at_the_original_path(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    a = scanned(write(zone / "a.bin", b"ours"))
    b = scanned(write(zone / "b.bin"))

    def newcomer() -> None:  # appears at the original path while we are moving
        write(a.path, b"newcomer")

    service = make_service(conn, policy, move=failing_on(2, OSError(5, "I/O"), before=newcomer))

    result = service.quarantine([Candidate(entry=a), Candidate(entry=b)])

    assert result.state is OperationState.FAILED
    assert a.path.read_bytes() == b"newcomer"
    assert rows(conn, "SELECT state FROM items ORDER BY id") == [
        ("quarantined",),  # still safe in the vault, restorable later
        ("rolled_back",),
    ]


def test_failed_move_back_keeps_the_item_quarantined(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    a = scanned(write(zone / "a.bin"))
    b = scanned(write(zone / "b.bin"))
    # call 1: a -> vault, call 2: b fails, call 3: moving a back fails too
    calls = {"n": 0}

    def move(source: Path, target: Path) -> object:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError(5, "I/O")
        return source.replace(target)

    result = make_service(conn, policy, move=move).quarantine(
        [Candidate(entry=a), Candidate(entry=b)]
    )

    assert result.state is OperationState.FAILED
    assert rows(conn, "SELECT state FROM items ORDER BY id") == [
        ("quarantined",),
        ("rolled_back",),
    ]


def test_rollback_where_the_rename_refuses_a_newcomer_keeps_the_item_quarantined(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    # [0016.8] on Windows the move back itself refuses a file that arrived after the check
    a = scanned(write(zone / "a.bin", b"ours"))
    b = scanned(write(zone / "b.bin"))
    calls = 0

    def move(source: Path, target: Path) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(5, "I/O")
        if calls == 3:  # moving a back: the newcomer lands between the check and the rename
            write(target, b"newcomer")
        windows_rename(source, target)
        return None

    result = make_service(conn, policy, move=move).quarantine(
        [Candidate(entry=a), Candidate(entry=b)]
    )

    assert result.state is OperationState.FAILED
    assert a.path.read_bytes() == b"newcomer"
    assert [item.original for item in result.moved] == [a.path]
    assert result.moved[0].vault_path.read_bytes() == b"ours"
    assert rows(conn, "SELECT state FROM items ORDER BY id") == [
        ("quarantined",),
        ("rolled_back",),
    ]


# --- recover -----------------------------------------------------------------------------------

JOURNAL_SIZE = 7  # len(b"payload")
JOURNAL_MTIME_NS = 1_000_000_000_000_000_000  # kept as it is by every system (NTFS: 100 ns)


def vault_file(slot: Path, data: bytes = b"payload", mtime_ns: int = JOURNAL_MTIME_NS) -> Path:
    """A file in a vault slot; by default it matches the journaled size and mtime_ns."""
    write(slot, data)
    os.utime(slot, ns=(mtime_ns, mtime_ns))
    return slot


def pending_item(
    conn: sqlite3.Connection, vault: Vault, original: Path, *, item_id: int = 1, op_id: int = 1
) -> Path:
    conn.execute(
        "INSERT OR IGNORE INTO operations (id, kind, state, created_at_ns)"
        " VALUES (?, 'quarantine', 'pending', 1)",
        (op_id,),
    )
    slot = vault.slot(op_id, item_id)
    conn.execute(
        "INSERT INTO items (id, operation_id, original_path, vault_path, size, mtime_ns, mode,"
        " state) VALUES (?, ?, ?, ?, ?, ?, 33188, 'pending')",
        (item_id, op_id, str(original), str(slot), JOURNAL_SIZE, JOURNAL_MTIME_NS),
    )
    return slot


def test_recover_marks_a_file_found_in_the_vault_as_quarantined(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path, data_dir: Path
) -> None:
    vault_file(pending_item(conn, Vault(data_dir), zone / "a.bin"))

    report = service.recover()

    assert report.quarantined == (zone / "a.bin",)
    assert report.warnings == ()
    assert rows(conn, "SELECT state FROM items") == [("quarantined",)]
    assert rows(conn, "SELECT state FROM operations") == [("done",)]


def test_recover_marks_a_file_still_at_home_as_rolled_back(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path, data_dir: Path
) -> None:
    pending_item(conn, Vault(data_dir), write(zone / "a.bin"))

    report = service.recover()

    assert report.rolled_back == (zone / "a.bin",)
    assert rows(conn, "SELECT state FROM operations") == [("rolled_back",)]


def test_recover_reports_a_file_found_nowhere_as_lost(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path, data_dir: Path
) -> None:
    pending_item(conn, Vault(data_dir), zone / "a.bin")

    report = service.recover()

    assert report.lost == (zone / "a.bin",)
    assert any(str(zone / "a.bin") in w for w in report.warnings)
    assert rows(conn, "SELECT state FROM items") == [("lost",)]
    assert rows(conn, "SELECT state FROM operations") == [("failed",)]


def test_recover_reports_a_vault_copy_of_another_size_as_lost(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path, data_dir: Path
) -> None:
    # Changed after the move: not the file we journaled, so never restored or purged as ours.
    vault_file(pending_item(conn, Vault(data_dir), zone / "a.bin"), b"overwritten, longer")

    report = service.recover()

    assert report.lost == (zone / "a.bin",)
    assert report.quarantined == ()
    assert any("changed" in w and str(zone / "a.bin") in w for w in report.warnings)
    assert rows(conn, "SELECT state FROM items") == [("lost",)]


def test_recover_reports_a_vault_copy_with_another_mtime_as_lost(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path, data_dir: Path
) -> None:
    slot = pending_item(conn, Vault(data_dir), zone / "a.bin")
    vault_file(slot, mtime_ns=JOURNAL_MTIME_NS + MTIME_STEP_NS)

    assert service.recover().lost == (zone / "a.bin",)


def test_recover_prefers_the_vault_copy_when_both_exist(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path, data_dir: Path
) -> None:
    # Rename is atomic, so a file at the original path is a newcomer; ours is in the vault.
    slot = pending_item(conn, Vault(data_dir), write(zone / "a.bin", b"newcomer"))
    vault_file(slot)
    assert service.recover().quarantined == (zone / "a.bin",)


def test_recover_mixed_outcomes_fail_the_operation(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path, data_dir: Path
) -> None:
    vault = Vault(data_dir)
    vault_file(pending_item(conn, vault, zone / "a.bin", item_id=1))
    pending_item(conn, vault, write(zone / "b.bin"), item_id=2)

    service.recover()

    assert rows(conn, "SELECT state FROM operations") == [("failed",)]


def test_recover_with_nothing_pending_changes_nothing(
    service: QuarantineService, conn: sqlite3.Connection
) -> None:
    report = service.recover()
    assert (report.quarantined, report.rolled_back, report.lost, report.warnings) == (
        (),
        (),
        (),
        (),
    )
    assert rows(conn, "SELECT COUNT(*) FROM operations") == [(0,)]


def test_after_recover_new_operations_are_allowed(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path, data_dir: Path
) -> None:
    pending_item(conn, Vault(data_dir), zone / "lost.bin")
    service.recover()
    a = scanned(write(zone / "a.bin"))
    assert service.quarantine([Candidate(entry=a)]).state is OperationState.DONE


def test_recover_leaves_an_intact_item_of_an_interrupted_rollback_quarantined(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    # Interrupted before its move back: still in the vault, still ours, nothing to report.
    a = scanned(write(zone / "a.bin"))
    service.quarantine([Candidate(entry=a)])
    conn.execute("UPDATE operations SET state = 'pending'")

    report = service.recover()

    assert report == RecoveryReport()
    assert rows(conn, "SELECT state FROM items") == [("quarantined",)]
    assert rows(conn, "SELECT state FROM operations") == [("done",)]


def test_recover_reports_a_tampered_item_of_an_interrupted_rollback_as_lost(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    a = scanned(write(zone / "a.bin"))
    result = service.quarantine([Candidate(entry=a)])
    conn.execute("UPDATE operations SET state = 'pending'")
    result.moved[0].vault_path.write_bytes(b"something else")

    report = service.recover()

    assert report.lost == (a.path,)
    assert len(report.warnings) == 1
    assert rows(conn, "SELECT state FROM items") == [("lost",)]
