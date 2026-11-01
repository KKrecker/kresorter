"""Purge: the only real deletion in safeclean (decision 0004, item 8).

Two steps. ``plan_purge`` reads the journal only and returns a plan for the user to confirm
(what, how many bytes). ``purge`` accepts exactly that plan, once, from the same service, and
deletes vault copies only: the original path is never touched. ``delete_from_vault`` is the
single function allowed to delete; it refuses anything that is not a regular file in a vault
slot ``<vault>/<operation>/<item>``.
"""

import dataclasses
import os
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy
from safeclean.core.heuristics import JunkClassifier
from safeclean.core.models import FileEntry
from safeclean.core.policy import PathPolicy
from safeclean.core.preflight import Candidate
from safeclean.quarantine.journal import OperationState
from safeclean.quarantine.purge import UnsafeDeleteError, delete_from_vault
from safeclean.quarantine.service import (
    PurgeError,
    PurgeRefusal,
    QuarantineError,
    QuarantineService,
    RestoreRefusal,
)
from safeclean.storage.db import connect
from support.files import write
from support.journal import rows

NO_RULES = JunkClassifier([], platform="linux")
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
    delete: Callable[[Path, Path], object] = delete_from_vault,
) -> QuarantineService:
    return QuarantineService(
        conn, policy=policy, open_files=FakeOpenFiles(), classifier=NO_RULES, delete=delete
    )


@pytest.fixture
def service(conn: sqlite3.Connection, policy: PathPolicy) -> QuarantineService:
    return make_service(conn, policy)


def quarantined(service: QuarantineService, path: Path, data: bytes = b"payload") -> int:
    """Put a fresh file at ``path`` into quarantine; return its item id."""
    write(path, data)
    os.utime(path, ns=(MTIME_NS, MTIME_NS))
    result = service.quarantine([Candidate(entry=scanned(path))])
    assert result.state is OperationState.DONE
    return result.moved[0].item_id


def slot_of(conn: sqlite3.Connection, item_id: int) -> Path:
    ((vault_path,),) = rows(conn, "SELECT vault_path FROM items WHERE id = ?", item_id)
    return Path(str(vault_path))


def item_state(conn: sqlite3.Connection, item_id: int) -> object:
    return rows(conn, "SELECT state FROM items WHERE id = ?", item_id)[0][0]


def purge_operations(conn: sqlite3.Connection) -> list[tuple[object, ...]]:
    return rows(conn, "SELECT state FROM operations WHERE kind = 'purge' ORDER BY id")


# --- delete_from_vault: the single deletion point ----------------------------------------------


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    return root


def test_deletes_a_regular_file_in_a_slot(vault_root: Path) -> None:
    slot = write(vault_root / "3" / "17")
    delete_from_vault(vault_root, slot)
    assert not slot.exists()
    assert (vault_root / "3").is_dir()  # only the file goes


def test_refuses_a_file_outside_the_vault(tmp_path: Path, vault_root: Path) -> None:
    outside = write(tmp_path / "home" / "3" / "17")
    with pytest.raises(UnsafeDeleteError, match="outside"):
        delete_from_vault(vault_root, outside)
    assert outside.exists()


@pytest.mark.parametrize(
    "relative",
    [
        "17",  # not under an operation directory
        "3/17/1",  # too deep
        "3/notes.txt",  # not an item id
        "x/17",  # not an operation id
        "../17",  # escapes lexically
        "3/../17",
    ],
)
def test_refuses_anything_but_a_slot_path(vault_root: Path, relative: str) -> None:
    target = vault_root / relative
    write(target.resolve())
    with pytest.raises(UnsafeDeleteError, match="slot"):
        delete_from_vault(vault_root, target)
    assert target.resolve().exists()


def test_refuses_a_relative_path(vault_root: Path) -> None:
    with pytest.raises(UnsafeDeleteError, match="absolute"):
        delete_from_vault(vault_root, Path("3") / "17")


def test_refuses_a_symlink_slot_and_keeps_its_target(tmp_path: Path, vault_root: Path) -> None:
    target = write(tmp_path / "precious.txt")
    (vault_root / "3").mkdir()
    (vault_root / "3" / "17").symlink_to(target)
    with pytest.raises(UnsafeDeleteError, match="regular"):
        delete_from_vault(vault_root, vault_root / "3" / "17")
    assert target.read_bytes() == b"payload"
    assert (vault_root / "3" / "17").is_symlink()


def test_refuses_a_directory_slot(vault_root: Path) -> None:
    (vault_root / "3" / "17").mkdir(parents=True)
    with pytest.raises(UnsafeDeleteError, match="regular"):
        delete_from_vault(vault_root, vault_root / "3" / "17")
    assert (vault_root / "3" / "17").is_dir()


def test_refuses_an_operation_directory_swapped_for_a_link(
    tmp_path: Path, vault_root: Path
) -> None:
    precious = write(tmp_path / "home" / "17")
    (vault_root / "3").symlink_to(tmp_path / "home", target_is_directory=True)
    with pytest.raises(UnsafeDeleteError, match="link"):
        delete_from_vault(vault_root, vault_root / "3" / "17")
    assert precious.exists()


def test_a_vault_reached_through_a_link_still_works(tmp_path: Path, vault_root: Path) -> None:
    # e.g. a symlinked home directory: only links *inside* the vault are suspicious.
    alias = tmp_path / "alias"
    alias.symlink_to(vault_root, target_is_directory=True)
    slot = write(vault_root / "3" / "17")
    delete_from_vault(alias, alias / "3" / "17")
    assert not slot.exists()


def test_missing_slot_is_an_os_error(vault_root: Path) -> None:
    (vault_root / "3").mkdir()
    with pytest.raises(FileNotFoundError):
        delete_from_vault(vault_root, vault_root / "3" / "17")


def test_unsafe_delete_is_not_an_os_error() -> None:
    # Callers treat OSError as "try again later"; an unsafe path is a bug, never retried.
    assert not issubclass(UnsafeDeleteError, OSError)


# --- plan_purge: read-only, for confirmation ---------------------------------------------------


def test_plan_lists_items_and_bytes_and_changes_nothing(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    first = quarantined(service, zone / "a.bin", b"aaa")
    second = quarantined(service, zone / "b.bin", b"bbbbb")

    plan = service.plan_purge([first, second])

    assert [(i.item_id, i.original, i.size) for i in plan.items] == [
        (first, zone / "a.bin", 3),
        (second, zone / "b.bin", 5),
    ]
    assert plan.total_bytes == 8
    assert plan.refused == ()
    assert plan.token
    assert slot_of(conn, first).exists()
    assert purge_operations(conn) == []
    assert item_state(conn, first) == "quarantined"


def test_plan_refuses_unknown_duplicate_and_not_quarantined_items(
    service: QuarantineService, zone: Path
) -> None:
    kept = quarantined(service, zone / "a.bin")
    restored = quarantined(service, zone / "b.bin")
    service.restore([restored])

    plan = service.plan_purge([kept, kept, 999, restored])

    assert [i.item_id for i in plan.items] == [kept]
    assert [(r.item_id, r.reason) for r in plan.refused] == [
        (kept, PurgeRefusal.DUPLICATE_ITEM),
        (999, PurgeRefusal.UNKNOWN_ITEM),
        (restored, PurgeRefusal.NOT_QUARANTINED),
    ]


def test_plan_tokens_are_unique(service: QuarantineService, zone: Path) -> None:
    item = quarantined(service, zone / "a.bin")
    assert service.plan_purge([item]).token != service.plan_purge([item]).token


# --- purge: happy path -------------------------------------------------------------------------


def test_purge_deletes_the_vault_copy_and_journals_it(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin", b"aaa")
    slot = slot_of(conn, item)

    result = service.purge(service.plan_purge([item]))

    assert result.state is OperationState.DONE
    assert [(p.item_id, p.original) for p in result.purged] == [(item, zone / "a.bin")]
    assert result.freed_bytes == 3
    assert result.refused == ()
    assert not slot.exists()
    assert item_state(conn, item) == "purged"
    assert purge_operations(conn) == [("done",)]
    assert rows(conn, "SELECT purge_operation_id FROM items") == [(result.operation_id,)]


def test_purge_never_touches_the_original_path(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    newcomer = write(zone / "a.bin", b"new file, same name")

    service.purge(service.plan_purge([item]))

    assert newcomer.read_bytes() == b"new file, same name"
    assert not slot_of(conn, item).exists()


def test_purged_item_cannot_be_restored_or_purged_again(
    service: QuarantineService, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    service.purge(service.plan_purge([item]))

    assert [r.reason for r in service.restore([item]).refused] == [RestoreRefusal.NOT_QUARANTINED]
    assert [r.reason for r in service.plan_purge([item]).refused] == [PurgeRefusal.NOT_QUARANTINED]


def test_plan_with_nothing_to_purge_journals_nothing(
    service: QuarantineService, conn: sqlite3.Connection
) -> None:
    result = service.purge(service.plan_purge([999]))
    assert result.operation_id is None
    assert result.state is None
    assert [r.reason for r in result.refused] == [PurgeRefusal.UNKNOWN_ITEM]
    assert purge_operations(conn) == []


# --- purge: the plan is a one-time confirmation ------------------------------------------------


def test_a_plan_is_accepted_only_once(service: QuarantineService, zone: Path) -> None:
    item = quarantined(service, zone / "a.bin")
    plan = service.plan_purge([item])
    service.purge(plan)
    with pytest.raises(PurgeError, match="plan"):
        service.purge(plan)


def test_a_plan_from_another_service_is_rejected(
    service: QuarantineService, conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    plan = service.plan_purge([item])
    with pytest.raises(PurgeError, match="plan"):
        make_service(conn, policy).purge(plan)
    assert slot_of(conn, item).exists()


def test_a_tampered_plan_is_rejected_and_burns_the_token(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    shown = quarantined(service, zone / "a.bin")
    hidden = quarantined(service, zone / "b.bin")
    plan = service.plan_purge([shown])
    extra = service.plan_purge([hidden]).items
    tampered = dataclasses.replace(plan, items=plan.items + extra)

    with pytest.raises(PurgeError, match="plan"):
        service.purge(tampered)
    with pytest.raises(PurgeError, match="plan"):
        service.purge(plan)
    assert slot_of(conn, shown).exists()
    assert slot_of(conn, hidden).exists()


def test_purge_error_is_a_quarantine_error() -> None:
    assert issubclass(PurgeError, QuarantineError)


# --- purge: per-item checks right before deleting ----------------------------------------------


def test_item_restored_after_planning_is_refused(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    plan = service.plan_purge([item])
    service.restore([item])

    result = service.purge(plan)

    assert [(r.item_id, r.reason) for r in result.refused] == [(item, PurgeRefusal.NOT_QUARANTINED)]
    assert result.operation_id is None
    assert (zone / "a.bin").read_bytes() == b"payload"


def test_changed_vault_copy_is_not_deleted_and_marked_lost(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    slot = slot_of(conn, item)
    plan = service.plan_purge([item])
    slot.write_bytes(b"something else entirely")  # not what the user agreed to delete

    result = service.purge(plan)

    assert [(r.item_id, r.reason) for r in result.refused] == [(item, PurgeRefusal.VAULT_CHANGED)]
    assert slot.read_bytes() == b"something else entirely"
    assert item_state(conn, item) == "lost"
    assert purge_operations(conn) == [("rolled_back",)]


def test_missing_vault_copy_is_refused_and_marked_lost(
    service: QuarantineService, conn: sqlite3.Connection, tmp_path: Path, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    plan = service.plan_purge([item])
    slot_of(conn, item).replace(tmp_path / "elsewhere")

    result = service.purge(plan)

    assert [r.reason for r in result.refused] == [PurgeRefusal.VAULT_MISSING]
    assert item_state(conn, item) == "lost"


def test_failed_delete_keeps_the_item_quarantined_and_others_proceed(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    def flaky(vault_root: Path, path: Path) -> None:
        if path.name == str(stuck):
            raise PermissionError("denied")
        delete_from_vault(vault_root, path)

    service = make_service(conn, policy, delete=flaky)
    stuck = quarantined(service, zone / "a.bin")
    gone = quarantined(service, zone / "b.bin", b"bb")

    result = service.purge(service.plan_purge([stuck, gone]))

    assert result.state is OperationState.FAILED
    assert [p.item_id for p in result.purged] == [gone]
    assert result.freed_bytes == 2
    assert [(r.item_id, r.reason) for r in result.refused] == [(stuck, PurgeRefusal.DELETE_FAILED)]
    assert "denied" in result.refused[0].detail
    assert slot_of(conn, stuck).exists()
    assert item_state(conn, stuck) == "quarantined"
    assert item_state(conn, gone) == "purged"


def test_nothing_deleted_rolls_the_operation_back(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    def broken(vault_root: Path, path: Path) -> None:
        raise PermissionError("denied")

    service = make_service(conn, policy, delete=broken)
    item = quarantined(service, zone / "a.bin")

    result = service.purge(service.plan_purge([item]))

    assert result.state is OperationState.ROLLED_BACK
    assert result.purged == ()
    assert purge_operations(conn) == [("rolled_back",)]


def test_unrecovered_journal_blocks_planning_and_purging(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    plan = service.plan_purge([item])
    conn.execute(
        "INSERT INTO operations (kind, state, created_at_ns) VALUES ('quarantine', 'pending', 1)"
    )
    with pytest.raises(QuarantineError, match="recover"):
        service.plan_purge([item])
    with pytest.raises(QuarantineError, match="recover"):
        service.purge(plan)
    assert slot_of(conn, item).exists()


def test_every_purge_refusal_has_a_case() -> None:
    assert {reason.value for reason in PurgeRefusal} == {
        "unknown_item",
        "duplicate_item",
        "not_quarantined",
        "vault_missing",
        "vault_changed",
        "delete_failed",
    }


# --- interrupted purge and recover() -----------------------------------------------------------


def test_interrupted_purge_is_left_for_recover(
    conn: sqlite3.Connection, policy: PathPolicy, zone: Path
) -> None:
    def crash_after_delete(vault_root: Path, path: Path) -> None:
        delete_from_vault(vault_root, path)
        raise KeyboardInterrupt  # the process dies before the journal learns about it

    service = make_service(conn, policy, delete=crash_after_delete)
    item = quarantined(service, zone / "a.bin")
    with pytest.raises(KeyboardInterrupt):
        service.purge(service.plan_purge([item]))
    assert purge_operations(conn) == [("pending",)]

    report = service.recover()

    assert report.purged == (zone / "a.bin",)
    assert item_state(conn, item) == "purged"
    assert purge_operations(conn) == [("done",)]


def pending_purge(conn: sqlite3.Connection, item_id: int) -> None:
    operation_id = conn.execute(
        "INSERT INTO operations (kind, state, created_at_ns) VALUES ('purge', 'pending', 1)"
    ).lastrowid
    conn.execute("UPDATE items SET purge_operation_id = ? WHERE id = ?", (operation_id, item_id))


def test_recover_keeps_an_intact_copy_quarantined(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    pending_purge(conn, item)

    report = service.recover()

    assert report.quarantined == (zone / "a.bin",)
    assert slot_of(conn, item).exists()
    assert item_state(conn, item) == "quarantined"
    assert purge_operations(conn) == [("rolled_back",)]


def test_recover_reports_a_changed_copy_as_lost(
    service: QuarantineService, conn: sqlite3.Connection, zone: Path
) -> None:
    item = quarantined(service, zone / "a.bin")
    pending_purge(conn, item)
    slot_of(conn, item).write_bytes(b"something else")

    report = service.recover()

    assert report.lost == (zone / "a.bin",)
    assert len(report.warnings) == 1
    assert "LOST" in report.warnings[0]
    assert slot_of(conn, item).exists()
