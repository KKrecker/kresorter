"""Restore from quarantine (decision 0004, item 6) and recovery of interrupted restores.

Timing-independent refusals (unknown, duplicate, not quarantined) happen before anything is
journaled. Disk checks (vault copy, conflict, parent chain) run per item right before its move,
after the restore operation is journaled, so they see the freshest state.
"""

import inspect
import os
import sqlite3
import stat
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy, windows_rename
from kresorter.core.heuristics import JunkClassifier
from kresorter.core.models import FileEntry
from kresorter.core.policy import PathPolicy
from kresorter.core.preflight import Candidate
from kresorter.quarantine.journal import OperationState
from kresorter.quarantine.service import QuarantineError, QuarantineService, RestoreRefusal
from kresorter.storage.db import connect
from support.files import write
from support.host import as_kept
from support.journal import rows

NO_RULES = JunkClassifier([], platform="linux")
ATIME_NS = 1_000_000_000_000_000_000
MTIME_NS = 1_100_000_000_000_000_000

# --- helpers -----------------------------------------------------------------------------------


def scanned(path: Path) -> FileEntry:
    info = path.lstat()
    return FileEntry(path=path, size=info.st_size, mtime_ns=info.st_mtime_ns)


@pytest.fixture
def policy(tmp_path: Path, zone: Path) -> PathPolicy:
    return make_policy(tmp_path, default_roots=[zone], app_data_dir=tmp_path / "data" / "sc")


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    (tmp_path / "journal").mkdir()
    connection = connect(tmp_path / "journal" / "journal.db")
    yield connection
    connection.close()


def make_service(
    conn: sqlite3.Connection,
    policy: PathPolicy,
    move: Callable[[Path, Path], object] = Path.rename,
) -> QuarantineService:
    return QuarantineService(
        conn, policy=policy, open_files=FakeOpenFiles(), classifier=NO_RULES, move=move
    )


@pytest.fixture
def service(conn: sqlite3.Connection, policy: PathPolicy) -> QuarantineService:
    return make_service(conn, policy)


def quarantined(service: QuarantineService, path: Path, data: bytes = b"payload") -> int:
    """Put a fresh file at ``path`` into quarantine; return its item id."""
    write(path, data)
    path.chmod(0o640)
    os.utime(path, ns=(ATIME_NS, MTIME_NS))
    result = service.quarantine([Candidate(entry=scanned(path))])
    assert result.state is OperationState.DONE
    return result.moved[0].item_id


def slot_of(conn: sqlite3.Connection, item_id: int) -> Path:
    ((vault_path,),) = rows(conn, "SELECT vault_path FROM items WHERE id = ?", item_id)
    return Path(str(vault_path))


def item_state(conn: sqlite3.Connection, item_id: int) -> object:
    return rows(conn, "SELECT state FROM items WHERE id = ?", item_id)[0][0]


# --- happy path --------------------------------------------------------------------------------


def test_file_goes_back_to_its_original_path(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin", b"aaa")

    result = service.restore([item])

    assert result.state is OperationState.DONE
    assert [(r.item_id, r.original) for r in result.restored] == [(item, zone / "a.bin")]
    assert result.refused == ()
    assert (zone / "a.bin").read_bytes() == b"aaa"
    assert not slot_of(conn, item).exists()
    assert item_state(conn, item) == "restored"
    assert rows(conn, "SELECT kind, state FROM operations ORDER BY id") == [
        ("quarantine", "done"),
        ("restore", "done"),
    ]
    assert rows(conn, "SELECT restore_operation_id FROM items") == [(result.operation_id,)]


def test_mode_atime_and_mtime_come_back_from_the_journal(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    slot = slot_of(conn, item)
    slot.chmod(0o600)  # touched in the vault: mode and atime differ, size and mtime do not
    os.utime(slot, ns=(5, MTIME_NS))

    service.restore([item])

    info = (zone / "a.bin").lstat()
    assert stat.S_IMODE(info.st_mode) == as_kept(0o640)
    assert info.st_atime_ns == ATIME_NS
    assert info.st_mtime_ns == MTIME_NS


def test_quarantine_journals_atime(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    assert rows(conn, "SELECT atime_ns FROM items WHERE id = ?", item) == [(ATIME_NS,)]


def test_legacy_item_without_atime_keeps_the_vault_atime(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    conn.execute("UPDATE items SET atime_ns = NULL WHERE id = ?", (item,))
    os.utime(slot_of(conn, item), ns=(7, MTIME_NS))

    service.restore([item])

    assert (zone / "a.bin").lstat().st_atime_ns == 7
    assert (zone / "a.bin").lstat().st_mtime_ns == MTIME_NS


def test_missing_parent_directories_are_recreated(service: QuarantineService, zone: Path) -> None:
    item = quarantined(service, zone / "deep" / "er" / "a.bin")
    (zone / "deep").replace(zone / "moved-away")  # the whole parent chain is gone

    result = service.restore([item])

    assert result.state is OperationState.DONE
    assert (zone / "deep" / "er" / "a.bin").read_bytes() == b"payload"


# --- refusals before journaling ----------------------------------------------------------------


def test_unknown_item_is_refused(service: QuarantineService, conn: sqlite3.Connection) -> None:
    result = service.restore([999])
    assert [(r.item_id, r.reason) for r in result.refused] == [(999, RestoreRefusal.UNKNOWN_ITEM)]
    assert result.operation_id is None
    assert rows(conn, "SELECT COUNT(*) FROM operations WHERE kind = 'restore'") == [(0,)]


def test_item_restored_twice_is_refused(service: QuarantineService, zone: Path) -> None:
    item = quarantined(service, zone / "a.bin")
    service.restore([item])
    result = service.restore([item])
    assert [r.reason for r in result.refused] == [RestoreRefusal.NOT_QUARANTINED]


@pytest.mark.parametrize("state", ["lost", "rolled_back", "purged"])
def test_item_in_another_state_is_refused(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path, state: str
) -> None:
    item = quarantined(service, zone / "a.bin")
    conn.execute("UPDATE items SET state = ? WHERE id = ?", (state, item))
    result = service.restore([item])
    assert [r.reason for r in result.refused] == [RestoreRefusal.NOT_QUARANTINED]
    assert slot_of(conn, item).exists()


def test_duplicate_item_in_one_call_is_refused(service: QuarantineService, zone: Path) -> None:
    item = quarantined(service, zone / "a.bin")
    result = service.restore([item, item])
    assert [r.item_id for r in result.restored] == [item]
    assert [(r.item_id, r.reason) for r in result.refused] == [
        (item, RestoreRefusal.DUPLICATE_ITEM)
    ]


def test_unrecovered_journal_blocks_restore(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    conn.execute(
        "INSERT INTO operations (kind, state, created_at_ns) VALUES ('quarantine', 'pending', 1)"
    )
    with pytest.raises(QuarantineError, match="recover"):
        service.restore([item])


# --- refusals right before the move ------------------------------------------------------------


def test_occupied_original_path_is_a_conflict_never_overwritten(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin", b"ours")
    write(zone / "a.bin", b"newcomer")

    result = service.restore([item])

    assert [r.reason for r in result.refused] == [RestoreRefusal.CONFLICT]
    assert result.state is OperationState.ROLLED_BACK  # journaled, nothing restored
    assert (zone / "a.bin").read_bytes() == b"newcomer"
    assert slot_of(conn, item).read_bytes() == b"ours"
    assert item_state(conn, item) == "quarantined"


def test_parent_swapped_for_symlink_is_refused(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path, tmp_path: Path
) -> None:
    item = quarantined(service, zone / "dir" / "a.bin")
    (zone / "dir").replace(zone / "old-dir")
    (tmp_path / "elsewhere").mkdir()
    (zone / "dir").symlink_to(tmp_path / "elsewhere")

    result = service.restore([item])

    assert [r.reason for r in result.refused] == [RestoreRefusal.PARENT_SWAPPED]
    assert list((tmp_path / "elsewhere").iterdir()) == []
    assert item_state(conn, item) == "quarantined"


def test_missing_vault_copy_is_refused_and_marked_lost(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    slot_of(conn, item).replace(zone / "taken-out-of-the-vault.bin")

    result = service.restore([item])

    assert [r.reason for r in result.refused] == [RestoreRefusal.VAULT_MISSING]
    assert item_state(conn, item) == "lost"


def test_changed_vault_copy_is_refused_and_marked_lost(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    # Decision 0006: a vault copy that differs from the journal is never restored as ours.
    item = quarantined(service, zone / "a.bin")
    slot = slot_of(conn, item)
    write(slot, b"overwritten, longer")

    result = service.restore([item])

    assert [r.reason for r in result.refused] == [RestoreRefusal.VAULT_CHANGED]
    assert not (zone / "a.bin").exists()
    assert item_state(conn, item) == "lost"


def test_failed_move_keeps_the_item_quarantined_and_others_proceed(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    service = make_service(conn, policy)
    first = quarantined(service, zone / "a.bin")
    second = quarantined(service, zone / "b.bin")
    calls = {"n": 0}

    def move(source: Path, target: Path) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(5, "I/O error")
        return source.replace(target)

    result = make_service(conn, policy, move).restore([first, second])

    assert result.state is OperationState.FAILED
    assert [(r.item_id, r.reason) for r in result.refused] == [(first, RestoreRefusal.MOVE_FAILED)]
    assert "I/O error" in result.refused[0].detail
    assert [r.item_id for r in result.restored] == [second]
    assert item_state(conn, first) == "quarantined"
    assert slot_of(conn, first).exists()


def test_the_quarantine_renames_and_never_replaces() -> None:
    # [0016.8] into the vault, back in a rollback, back in a restore: Path.rename, which on
    # Windows fails where a file is; on Linux the same rename(2) as before
    assert inspect.signature(QuarantineService).parameters["move"].default is Path.rename


def test_a_newcomer_after_the_check_is_a_conflict_where_the_rename_refuses_it(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    # [0016.8] on Windows: the file there is never overwritten, the copy stays restorable
    item = quarantined(make_service(conn, policy), zone / "a.bin", b"ours")

    def arriving(source: Path, target: Path) -> None:
        write(target, b"newcomer")  # between the check and the rename
        windows_rename(source, target)

    result = make_service(conn, policy, arriving).restore([item])

    assert [(r.reason, r.detail) for r in result.refused] == [
        (RestoreRefusal.CONFLICT, str(zone / "a.bin"))
    ]
    assert (zone / "a.bin").read_bytes() == b"newcomer"
    assert slot_of(conn, item).read_bytes() == b"ours"
    assert item_state(conn, item) == "quarantined"


def test_a_parent_that_became_a_file_is_a_failed_move_not_a_conflict(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    # [0016.8] only the rename's own refusal is a conflict
    item = quarantined(service, zone / "dir" / "a.bin")
    (zone / "dir").rename(zone / "old-dir")
    write(zone / "dir", b"a file now")

    result = service.restore([item])

    assert [r.reason for r in result.refused] == [RestoreRefusal.MOVE_FAILED]
    assert item_state(conn, item) == "quarantined"


def test_every_restore_refusal_has_a_case() -> None:
    assert {r.value for r in RestoreRefusal} == {
        "unknown_item",
        "duplicate_item",
        "not_quarantined",
        "vault_missing",
        "vault_changed",
        "conflict",
        "parent_swapped",
        "move_failed",
    }


# --- interrupted restore and recover() ---------------------------------------------------------


def test_interrupted_restore_is_left_for_recover(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    item = quarantined(make_service(conn, policy), zone / "a.bin")

    def interrupt(source: Path, target: Path) -> object:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        make_service(conn, policy, interrupt).restore([item])
    assert rows(conn, "SELECT state FROM operations WHERE kind = 'restore'") == [("pending",)]

    service = make_service(conn, policy)
    report = service.recover()

    assert report.quarantined == (zone / "a.bin",)  # the vault copy never left
    assert item_state(conn, item) == "quarantined"
    assert rows(conn, "SELECT state FROM operations WHERE kind = 'restore'") == [("rolled_back",)]
    assert service.restore([item]).state is OperationState.DONE


def pending_restore(conn: sqlite3.Connection, item_id: int) -> None:
    """Journal state of a restore that crashed after its operation was committed."""
    cursor = conn.execute(
        "INSERT INTO operations (kind, state, created_at_ns) VALUES ('restore', 'pending', 1)"
    )
    conn.execute(
        "UPDATE items SET restore_operation_id = ? WHERE id = ?", (cursor.lastrowid, item_id)
    )


def test_recover_finishes_a_restore_whose_move_happened(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    pending_restore(conn, item)
    slot_of(conn, item).replace(zone / "a.bin")  # the move happened, the journal update did not

    report = service.recover()

    assert report.restored == (zone / "a.bin",)
    assert item_state(conn, item) == "restored"
    assert rows(conn, "SELECT state FROM operations WHERE kind = 'restore'") == [("done",)]


def test_recover_reports_a_restore_found_nowhere_as_lost(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    pending_restore(conn, item)
    slot_of(conn, item).replace(zone / "elsewhere.bin")

    report = service.recover()

    assert report.lost == (zone / "a.bin",)
    assert any(str(zone / "a.bin") in w for w in report.warnings)
    assert item_state(conn, item) == "lost"
    assert rows(conn, "SELECT state FROM operations WHERE kind = 'restore'") == [("failed",)]


def test_recover_does_not_take_a_different_file_at_home_for_the_restored_one(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    pending_restore(conn, item)
    slot_of(conn, item).replace(zone / "elsewhere.bin")
    write(zone / "a.bin", b"a different, longer file")

    assert service.recover().lost == (zone / "a.bin",)
