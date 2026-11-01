"""The planner, read-only (decision 0012, items 1-6 and 9-20): what would move where, and why
every other entry of the folder stays. The folder itself, refused as a whole, is tested in
``test_organize_folders.py``.

Every test plans a real temporary folder, ``zone/Downloads``. Names that keep a file in place
are compared after NFC and ``casefold`` on every platform (item 20): a wrong match only keeps a
file in place, a missed one moves it away from what expects it. Linux keeps ``café`` written
precomposed and decomposed as two names, so both spellings can be made side by side here.
"""

import os
from pathlib import Path

import pytest

from fakes import deny_stat, relist
from safeclean.core.scanner import ScanContext
from safeclean.organize.planner import Move, Plan, Stay, StayReason, plan
from support.files import write

NFC = "caf\u00e9"  # é as one code point
NFD = "cafe\u0301"  # e and a combining acute accent, as a Mac writes it


def downloads(zone: Path, *names: str) -> Path:
    """``zone/Downloads``, holding a file for each of ``names`` (``a/b`` makes ``a`` too)."""
    folder = zone / "Downloads"
    folder.mkdir()
    for name in names:
        write(folder / name)
    return folder


def moved(result: Plan) -> dict[str, str]:
    return {move.source.name: move.category for move in result.moves}


def stayed(result: Plan) -> dict[str, StayReason]:
    return {stay.path.name: stay.reason for stay in result.stays}


def state(root: Path) -> list[tuple[str, bool, int]]:
    """``root`` and everything under it: each path, whether a directory, its ``mtime_ns``."""
    return sorted(
        (p.as_posix(), p.is_dir(), p.lstat().st_mtime_ns) for p in [root, *root.rglob("*")]
    )


# --- proposing changes nothing (item 1) ---------------------------------------------------------


def test_planning_makes_moves_and_writes_nothing(zone: Path, scan: ScanContext) -> None:
    # [0012.1] no category directory, no file moved or touched, the folder not even written
    folder = downloads(zone, "a.jpg", "b.pdf", "c.mp3", "notes.xyz")
    before = state(zone)
    assert len(plan(folder, scan).moves) == 3
    assert state(zone) == before


# --- one folder, one level, a move stays in it (items 2 and 3) ----------------------------------


def test_subdirectories_are_never_entered_nor_moved(zone: Path, scan: ScanContext) -> None:
    # [0012.2] whatever they hold, even what would refuse the folder itself (item 8)
    folder = downloads(zone, "album/a.jpg", "app/Makefile", "repo/.git/HEAD", "b.pdf")
    result = plan(folder, scan)
    assert moved(result) == {"b.pdf": "Documents"}
    assert stayed(result) == {
        "album": StayReason.NOT_REGULAR,
        "app": StayReason.NOT_REGULAR,
        "repo": StayReason.NOT_REGULAR,
    }


def test_a_file_goes_one_level_down_under_its_own_name(zone: Path, scan: ScanContext) -> None:
    # [0012.3] with the size and mtime_ns the plan saw
    folder = downloads(zone, "Report 2026.PDF")
    info = (folder / "Report 2026.PDF").lstat()
    (move,) = plan(folder, scan).moves
    assert move == Move(folder / "Report 2026.PDF", "Documents", info.st_size, info.st_mtime_ns)
    assert move.destination == folder / "Documents" / "Report 2026.PDF"


# --- every entry is reported (item 5) -----------------------------------------------------------


def test_the_stay_reasons_are_pinned() -> None:
    # [0012.5] adding or removing one is a decision of its own; missing is for undo (item 30)
    assert [reason.value for reason in StayReason] == [
        "not_regular",
        "folder_metadata",
        "in_progress",
        "junk",
        "unknown_kind",
        "companion",
        "program",
        "conflict",
        "category_blocked",
        "missing",
    ]


def test_every_entry_moves_or_stays_with_its_reason(zone: Path, scan: ScanContext) -> None:
    # [0012.5] never skipped in silence: each entry once, in moves or in stays
    folder = downloads(zone, "a.jpg", "a.xmp", "b.pdf", ".hidden", "x.tmp", "y.part", "sub/c.mp3")
    result = plan(folder, scan)
    planned = [move.source for move in result.moves] + [stay.path for stay in result.stays]
    assert sorted(planned) == sorted(folder.iterdir())


# --- deterministic (item 6) ---------------------------------------------------------------------


def test_the_plan_does_not_depend_on_the_listing_order(
    zone: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.6]
    folder = downloads(zone, "b.mp3", "a.pdf", "c.jpg", "a.jpg", "z.txt", "notes.xyz", "x.tmp")
    relist(monkeypatch, folder, sorted)
    in_order = plan(folder, scan)
    relist(monkeypatch, folder, lambda names: sorted(names, reverse=True))
    assert plan(folder, scan) == in_order


def test_moves_go_by_category_in_table_order_then_by_name(zone: Path, scan: ScanContext) -> None:
    # [0012.6] Images, Videos, Audio, Documents, Archives, Installers
    folder = downloads(zone, "setup.msi", "b.mp3", "doc.pdf", "a.mp3", "z.jpg", "clip.mp4")
    names = [move.source.name for move in plan(folder, scan).moves]
    assert names == ["z.jpg", "clip.mp4", "a.mp3", "b.mp3", "doc.pdf", "setup.msi"]


def test_stays_go_by_reason_in_pinned_order_then_by_name(zone: Path, scan: ScanContext) -> None:
    # [0012.6]
    folder = downloads(zone, "b.xyz", "a.xyz", ".hidden", "dir/x", "x.tmp")
    names = [stay.path.name for stay in plan(folder, scan).stays]
    assert names == ["dir", ".hidden", "x.tmp", "a.xyz", "b.xyz"]


# --- what stays (items 9-18) --------------------------------------------------------------------


def test_anything_but_a_regular_file_stays(tmp_path: Path, zone: Path, scan: ScanContext) -> None:
    # [0012.9] links are never followed, whatever they lead to
    folder = downloads(zone, "report.pdf")
    (folder / "album").mkdir()
    (folder / "photo.jpg").symlink_to(folder / "report.pdf")
    (folder / "elsewhere").symlink_to(tmp_path)
    (folder / "song.mp3").symlink_to(folder / "missing.mp3")
    os.mkfifo(folder / "clip.mp4")
    result = plan(folder, scan)
    assert moved(result) == {"report.pdf": "Documents"}
    assert stayed(result) == {
        name: StayReason.NOT_REGULAR
        for name in ("album", "clip.mp4", "elsewhere", "photo.jpg", "song.mp3")
    }


def test_the_folders_own_metadata_stays(zone: Path, scan: ScanContext) -> None:
    # [0012.10] before junk: Thumbs.db and .DS_Store are junk rules too
    folder = downloads(zone, ".DS_Store", ".hidden.jpg", "desktop.ini", "Thumbs.db")
    assert stayed(plan(folder, scan)) == {
        ".DS_Store": StayReason.FOLDER_METADATA,
        ".hidden.jpg": StayReason.FOLDER_METADATA,
        "Thumbs.db": StayReason.FOLDER_METADATA,
        "desktop.ini": StayReason.FOLDER_METADATA,
    }


def test_work_in_progress_stays(zone: Path, scan: ScanContext) -> None:
    # [0012.11] partial downloads and Office lock files
    names = ("film.mkv.part", "setup.exe.crdownload", "x.zip.download", "y.iso.partial")
    folder = downloads(zone, *names, "~$report.docx")
    assert stayed(plan(folder, scan)) == {
        name: StayReason.IN_PROGRESS for name in (*names, "~$report.docx")
    }


def test_junk_stays_for_analyze_and_the_quarantine(zone: Path, scan: ScanContext) -> None:
    # [0012.12] the detail is the junk rule
    folder = downloads(zone, "draft.tmp", "ehthumbs.db", "page.temp")
    assert [(s.path.name, s.reason, s.detail) for s in plan(folder, scan).stays] == [
        ("draft.tmp", StayReason.JUNK, "temp-files"),
        ("ehthumbs.db", StayReason.JUNK, "thumbs-db"),
        ("page.temp", StayReason.JUNK, "temp-files"),
    ]


def test_a_file_of_unknown_kind_stays(zone: Path, scan: ScanContext) -> None:
    # [0012.13] [0012.16] no Other; a web page is not in the table
    folder = downloads(zone, "notes.xyz", "README", "page.html", "old.htm", "data.tar.unknown")
    assert set(stayed(plan(folder, scan)).values()) == {StayReason.UNKNOWN_KIND}


def test_a_saved_page_keeps_what_it_loads(zone: Path, scan: ScanContext) -> None:
    # [0012.14] [0012.16] the page stays, so the picture it shows stays beside it
    folder = downloads(zone, "page.html", "page_files/style.css", "page.png", "other.png")
    result = plan(folder, scan)
    assert stayed(result) == {
        "page.html": StayReason.UNKNOWN_KIND,
        "page.png": StayReason.COMPANION,
        "page_files": StayReason.NOT_REGULAR,
    }
    assert moved(result) == {"other.png": "Images"}


@pytest.mark.parametrize(
    "pair",
    [
        ("film.mkv", "film.srt"),  # a video and its subtitles
        ("photo.jpg", "photo.xmp"),  # a photo and its sidecar
        ("song.mp3", "song.jpg"),  # a song and its cover: two categories
        ("holiday.2026.mp4", "holiday.jpg"),  # the stem is the name before its first dot
        ("report.pdf", "report.pdf.part"),  # one that stays for another reason
        ("notes.txt", "notes"),
    ],
)
def test_companions_stay_together(zone: Path, scan: ScanContext, pair: tuple[str, str]) -> None:
    # [0012.14]
    result = plan(downloads(zone, *pair, "other.pdf"), scan)
    assert stayed(result)[pair[0]] is StayReason.COMPANION
    assert moved(result) == {"other.pdf": "Documents"}


def test_companions_of_one_category_move_together(zone: Path, scan: ScanContext) -> None:
    # [0012.14]
    result = plan(downloads(zone, "album.flac", "album.mp3", "album.m4a"), scan)
    assert moved(result) == {"album.flac": "Audio", "album.mp3": "Audio", "album.m4a": "Audio"}


def test_a_link_is_a_companion_and_a_directory_is_not(zone: Path, scan: ScanContext) -> None:
    # [0012.14] a directory is a unit of its own (item 2); a link may be what a file expects
    folder = downloads(zone, "film.mkv", "song.mp3", "song/cover.jpg")
    (folder / "film.srt").symlink_to(folder / "song" / "cover.jpg")
    result = plan(folder, scan)
    assert stayed(result)["film.mkv"] is StayReason.COMPANION
    assert moved(result) == {"song.mp3": "Audio"}


@pytest.mark.parametrize("library", ["engine.dll", "libfoo.so", "libfoo.so.6", "libfoo.dylib"])
def test_programs_next_to_their_libraries_stay(zone: Path, scan: ScanContext, library: str) -> None:
    # [0012.15] the library is of no kind; an installer still moves
    result = plan(downloads(zone, "game.exe", library, "setup.msi"), scan)
    assert stayed(result) == {"game.exe": StayReason.PROGRAM, library: StayReason.UNKNOWN_KIND}
    assert moved(result) == {"setup.msi": "Installers"}


def test_a_lone_program_is_an_installer(zone: Path, scan: ScanContext) -> None:
    # [0012.15]
    assert moved(plan(downloads(zone, "setup.exe", "tool.msi"), scan)) == {
        "setup.exe": "Installers",
        "tool.msi": "Installers",
    }


def test_a_taken_destination_leaves_the_file_in_place(
    tmp_path: Path, zone: Path, scan: ScanContext
) -> None:
    # [0012.4] [0012.17] a file, a directory or a link, even one leading nowhere
    folder = downloads(zone, "a.jpg", "b.jpg", "c.jpg", "d.jpg", "Images/a.jpg", "Images/b.jpg/x")
    (folder / "Images" / "c.jpg").symlink_to(tmp_path / "nowhere")
    result = plan(folder, scan)
    assert stayed(result) == {
        "Images": StayReason.NOT_REGULAR,
        "a.jpg": StayReason.CONFLICT,
        "b.jpg": StayReason.CONFLICT,
        "c.jpg": StayReason.CONFLICT,
    }
    assert moved(result) == {"d.jpg": "Images"}


def test_a_destination_that_cannot_be_looked_at_counts_as_taken(
    zone: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.17] whether it is free is asked of the file system, which does not answer
    folder = downloads(zone, "a.jpg", "Images/other.jpg")
    deny_stat(monkeypatch, folder / "Images" / "a.jpg")
    (stay,) = [s for s in plan(folder, scan).stays if s.path.name == "a.jpg"]
    assert stay == Stay(folder / "a.jpg", StayReason.CONFLICT, "Permission denied")


def test_a_category_path_that_is_not_a_directory_keeps_its_category(
    tmp_path: Path, zone: Path, scan: ScanContext
) -> None:
    # [0012.18] Images is a file, Documents a link to a directory: never followed
    (tmp_path / "elsewhere").mkdir()
    folder = downloads(zone, "Images", "a.jpg", "b.png", "c.pdf", "d.mp3")
    (folder / "Documents").symlink_to(tmp_path / "elsewhere")
    result = plan(folder, scan)
    assert stayed(result) == {
        "Documents": StayReason.NOT_REGULAR,
        "Images": StayReason.UNKNOWN_KIND,
        "a.jpg": StayReason.CATEGORY_BLOCKED,
        "b.png": StayReason.CATEGORY_BLOCKED,
        "c.pdf": StayReason.CATEGORY_BLOCKED,
    }
    assert moved(result) == {"d.mp3": "Audio"}


def test_a_category_path_that_cannot_be_looked_at_keeps_its_category(
    zone: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.18]
    folder = downloads(zone, "a.jpg")
    deny_stat(monkeypatch, folder / "Images")
    (stay,) = plan(folder, scan).stays
    assert stay == Stay(folder / "a.jpg", StayReason.CATEGORY_BLOCKED, "Permission denied")


def test_a_file_gone_since_the_listing_is_not_planned(
    zone: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.5] it is not in the folder any more: nothing to report
    folder = downloads(zone, "a.jpg")
    relist(monkeypatch, folder, lambda names: [*names, "gone.pdf"])
    result = plan(folder, scan)
    assert (moved(result), stayed(result)) == ({"a.jpg": "Images"}, {})


# --- folded names (item 20) ---------------------------------------------------------------------


def test_subtitles_keep_their_film_whatever_the_case(zone: Path, scan: ScanContext) -> None:
    # [0012.14] [0012.20] Movie.mkv and movie.srt are one film
    result = plan(downloads(zone, "Movie.mkv", "movie.srt", "report.pdf"), scan)
    assert stayed(result) == {
        "Movie.mkv": StayReason.COMPANION,
        "movie.srt": StayReason.UNKNOWN_KIND,
    }
    assert moved(result) == {"report.pdf": "Documents"}


def test_companions_of_one_category_move_together_whatever_the_case(
    zone: Path, scan: ScanContext
) -> None:
    # [0012.14] [0012.20]
    result = plan(downloads(zone, "Song.mp3", "song.FLAC"), scan)
    assert moved(result) == {"Song.mp3": "Audio", "song.FLAC": "Audio"}
    assert stayed(result) == {}


def test_a_sidecar_keeps_its_photo_across_unicode_normalizations(
    zone: Path, scan: ScanContext
) -> None:
    # [0012.14] [0012.20] the photo written precomposed, its sidecar decomposed
    folder = downloads(zone, f"{NFC}.jpg", f"{NFD}.xmp")
    assert len(list(folder.iterdir())) == 2  # two names on this file system
    assert stayed(plan(folder, scan)) == {
        f"{NFC}.jpg": StayReason.COMPANION,
        f"{NFD}.xmp": StayReason.UNKNOWN_KIND,
    }


def test_case_and_normalization_fold_together(zone: Path, scan: ScanContext) -> None:
    # [0012.20] upper case precomposed, lower case decomposed
    result = plan(downloads(zone, "CAF\u00c9.JPG", f"{NFD}.xmp"), scan)
    assert stayed(result)["CAF\u00c9.JPG"] is StayReason.COMPANION


def test_folding_is_not_fuzzy(zone: Path, scan: ScanContext) -> None:
    # [0012.20] café and cafe are two stems: the photo moves
    result = plan(downloads(zone, f"{NFC}.jpg", "cafe.xmp"), scan)
    assert moved(result) == {f"{NFC}.jpg": "Images"}


def test_metadata_and_work_in_progress_are_found_whatever_the_case(
    zone: Path, scan: ScanContext
) -> None:
    # [0012.10] [0012.11] [0012.20]
    folder = downloads(zone, "THUMBS.DB", "Desktop.INI", "film.mkv.PART", "setup.exe.CRDOWNLOAD")
    assert stayed(plan(folder, scan)) == {
        "Desktop.INI": StayReason.FOLDER_METADATA,
        "THUMBS.DB": StayReason.FOLDER_METADATA,
        "film.mkv.PART": StayReason.IN_PROGRESS,
        "setup.exe.CRDOWNLOAD": StayReason.IN_PROGRESS,
    }


def test_a_library_in_capitals_keeps_its_program(zone: Path, scan: ScanContext) -> None:
    # [0012.15] [0012.20]
    result = plan(downloads(zone, "game.exe", "ENGINE.DLL"), scan)
    assert stayed(result)["game.exe"] is StayReason.PROGRAM


def test_an_office_lock_file_is_found_across_normalizations(zone: Path, scan: ScanContext) -> None:
    # [0012.11] [0012.20] the lock of a document named in decomposed form
    result = plan(downloads(zone, f"~${NFD}.DOCX"), scan)
    assert stayed(result) == {f"~${NFD}.DOCX": StayReason.IN_PROGRESS}
