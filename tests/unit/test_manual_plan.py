"""Manual plans select only assigned regular files and keep the usual safety rules."""

from pathlib import Path

import pytest

from kresorter.core.scanner import ScanContext
from kresorter.organize.manual import plan_manual
from kresorter.organize.planner import StayReason
from support.files import write


def test_only_assigned_files_are_proposed_without_writing(zone: Path, scan: ScanContext) -> None:
    folder = zone / "Downloads"
    write(folder / "photo.jpg", b"photo")
    write(folder / "note.xyz", b"note")
    write(folder / "other.pdf", b"other")
    result = plan_manual(folder, scan, {"photo.jpg": "Trip", "note.xyz": "Notes"})
    assert [(m.source.name, m.category) for m in result.moves] == [
        ("note.xyz", "Notes"),
        ("photo.jpg", "Trip"),
    ]
    assert result.stays == ()
    assert sorted(p.name for p in folder.iterdir()) == ["note.xyz", "other.pdf", "photo.jpg"]


def test_unassigned_companion_keeps_file_in_place(zone: Path, scan: ScanContext) -> None:
    folder = zone / "Downloads"
    write(folder / "song.mp3")
    write(folder / "song.lrc")
    result = plan_manual(folder, scan, {"song.mp3": "Audio"})
    assert result.moves == ()
    assert [(s.path.name, s.reason) for s in result.stays] == [("song.mp3", StayReason.COMPANION)]


def test_protected_items_and_directories_are_not_moved(zone: Path, scan: ScanContext) -> None:
    folder = zone / "Downloads"
    write(folder / "project" / "file.txt")
    write(folder / ".hidden")
    write(folder / "active.part")
    result = plan_manual(
        folder, scan, {name: "Group" for name in ("project", ".hidden", "active.part")}
    )
    assert result.moves == ()
    assert {s.path.name: s.reason for s in result.stays} == {
        "project": StayReason.NOT_REGULAR,
        ".hidden": StayReason.FOLDER_METADATA,
        "active.part": StayReason.IN_PROGRESS,
    }


@pytest.mark.parametrize("group", ["../escape", "CON", "", "hello/there", "trailing."])
def test_invalid_group_is_rejected(zone: Path, scan: ScanContext, group: str) -> None:
    folder = zone / "Downloads"
    write(folder / "a.txt")
    with pytest.raises(ValueError, match="invalid group name"):
        plan_manual(folder, scan, {"a.txt": group})


def test_unknown_name_is_rejected(zone: Path, scan: ScanContext) -> None:
    folder = zone / "Downloads"
    write(folder / "a.txt")
    with pytest.raises(ValueError, match="assigned name"):
        plan_manual(folder, scan, {"../a.txt": "Group"})


def test_assigned_companions_can_move_together(zone: Path, scan: ScanContext) -> None:
    folder = zone / "Downloads"
    write(folder / "song.mp3")
    write(folder / "song.lrc")
    result = plan_manual(folder, scan, {"song.mp3": "Music", "song.lrc": "Music"})
    assert {m.source.name for m in result.moves} == {"song.mp3", "song.lrc"}


def test_unassigned_directory_is_not_a_companion(zone: Path, scan: ScanContext) -> None:
    folder = zone / "Downloads"
    write(folder / "song.mp3")
    write(folder / "song" / "data.txt")
    result = plan_manual(folder, scan, {"song.mp3": "Music"})
    assert [m.source.name for m in result.moves] == ["song.mp3"]


def test_a_taken_destination_stays(zone: Path, scan: ScanContext) -> None:
    folder = zone / "Downloads"
    write(folder / "a.txt", b"original")
    write(folder / "Group" / "a.txt", b"existing")
    result = plan_manual(folder, scan, {"a.txt": "Group"})
    assert result.moves == ()
    assert result.stays[0].reason is StayReason.CONFLICT
    assert (folder / "Group" / "a.txt").read_bytes() == b"existing"


def test_unreadable_companion_is_conservatively_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fakes import deny_stat
    from kresorter.organize.manual import _is_companion

    path = tmp_path / "gone"
    deny_stat(monkeypatch, path)
    assert _is_companion(path)
