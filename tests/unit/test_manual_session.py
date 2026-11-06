"""Manual file moves use the same journal, revalidation and undo as automatic moves."""

from pathlib import Path

from kresorter.core.scanner import ScanContext
from kresorter.organize.manual import plan_manual
from kresorter.organize.undo import UndoPlan
from kresorter.ui.sessions import (
    Carried,
    Organized,
    in_organize,
    sort_manual_folder,
    undo_batch,
    undo_plan,
)
from support.files import write


def test_manual_batch_moves_only_confirmed_assignments_and_can_be_undone(
    zone: Path, scan: ScanContext
) -> None:
    folder = zone / "Downloads"
    write(folder / "a.txt", b"a")
    write(folder / "b.txt", b"b")
    assignments = {"a.txt": "My group"}
    before = plan_manual(folder, scan, assignments)
    result = in_organize(scan, sort_manual_folder(folder, before.moves, assignments))
    assert isinstance(result, Organized)
    assert isinstance(result.result, Carried)
    assert result.result.batch is not None
    assert (folder / "My group" / "a.txt").read_bytes() == b"a"
    assert (folder / "b.txt").read_bytes() == b"b"
    batch_id = result.result.batch.batch_id
    undo = in_organize(scan, undo_plan(batch_id))
    assert isinstance(undo, Organized)
    assert isinstance(undo.result, UndoPlan)
    restored = in_organize(scan, undo_batch(batch_id, undo.result.moves))
    assert isinstance(restored, Organized)
    assert (folder / "a.txt").read_bytes() == b"a"


def test_changed_file_is_not_moved(zone: Path, scan: ScanContext) -> None:
    folder = zone / "Downloads"
    file = write(folder / "a.txt", b"original")
    assignments = {"a.txt": "Group"}
    confirmed = plan_manual(folder, scan, assignments)
    write(file, b"changed and longer")
    result = in_organize(scan, sort_manual_folder(folder, confirmed.moves, assignments))
    assert isinstance(result, Organized)
    assert isinstance(result.result, Carried)
    assert result.result.batch is None
    assert result.result.changed == (file,)
    assert file.read_bytes() == b"changed and longer"


def test_missing_assigned_file_aborts_safely(zone: Path, scan: ScanContext) -> None:
    folder = zone / "Downloads"
    file = write(folder / "a.txt")
    assignments = {"a.txt": "Group"}
    confirmed = plan_manual(folder, scan, assignments)
    file.rename(folder / "renamed.txt")
    result = in_organize(scan, sort_manual_folder(folder, confirmed.moves, assignments))
    assert isinstance(result, Organized)
    assert isinstance(result.result, Carried)
    assert result.result.batch is None
    assert result.result.changed == (file,)
    assert not (folder / "Group").exists()


def test_manual_preview_refuses_a_folder_that_became_a_project(
    zone: Path, scan: ScanContext
) -> None:
    from kresorter.organize.folders import FolderRefused
    from kresorter.ui.sessions import plan_manual_folder

    folder = zone / "Downloads"
    write(folder / "a.txt")
    write(folder / "Makefile")
    preview = in_organize(scan, plan_manual_folder(folder, {"a.txt": "Group"}))
    assert isinstance(preview, Organized)
    assert isinstance(preview.result, FolderRefused)
    action = in_organize(scan, sort_manual_folder(folder, (), {"a.txt": "Group"}))
    assert isinstance(action, Organized)
    assert isinstance(action.result, FolderRefused)
