"""On Windows a move never makes a path past the limit (decision 0017, items 6 and 7).

A category directory has at most 247 characters and a destination 259, counted in UTF-16 code
units as Windows counts them, with or without long paths. The folders here are made deep enough
under ``zone`` that a category directory has the length a test wants; this machine's paths take
``/`` where Windows takes ``\\``, one character either way.
"""

import dataclasses
from pathlib import Path

import pytest

from fakes import deny_stat
from kresorter.core.scanner import ScanContext
from kresorter.organize.planner import Plan, StayReason, plan
from kresorter.ui.i18n import Translator
from support.files import write

DIRECTORY = 247
DESTINATION = 259


@pytest.fixture
def windows(scan: ScanContext) -> ScanContext:
    return dataclasses.replace(scan, platform="windows")


def folder_of(zone: Path, length: int, category: str) -> Path:
    """``Downloads``, deep enough under ``zone`` that ``<folder>/<category>`` has ``length``
    characters."""
    pad = length - len(str(zone / "Downloads" / category)) - 1
    folder = zone / ("p" * pad) / "Downloads"
    folder.mkdir(parents=True)
    assert len(str(folder / category)) == length
    return folder


def named(folder: Path, category: str, length: int, suffix: str, first: str = "n") -> str:
    """A name whose destination ``<folder>/<category>/<name>`` has ``length`` characters."""
    room = length - len(str(folder / category)) - 1 - len(first) - len(suffix)
    return first + "n" * room + suffix


def stays(found: Plan) -> list[tuple[str, StayReason, str]]:
    return [(s.path.name, s.reason, s.detail) for s in found.stays]


def moved(found: Plan) -> list[str]:
    return [m.source.name for m in found.moves]


def test_a_category_directory_past_247_keeps_its_files(zone: Path, windows: ScanContext) -> None:
    # [0017.6] Documents would have 248 characters; Images, three shorter, is used
    folder = folder_of(zone, DIRECTORY + 1, "Documents")
    write(folder / "b.pdf", b"b.pdf")
    write(folder / "a.jpg", b"a.jpg")
    found = plan(folder, windows)
    detail = f"{folder / 'Documents'}: 248 > 247"
    assert stays(found) == [("b.pdf", StayReason.PATH_TOO_LONG, detail)]
    assert moved(found) == ["a.jpg"]


def test_a_category_directory_of_247_is_used(zone: Path, windows: ScanContext) -> None:
    # [0017.6]
    folder = folder_of(zone, DIRECTORY, "Documents")
    write(folder / "b.pdf", b"b.pdf")
    assert moved(plan(folder, windows)) == ["b.pdf"]


def test_a_destination_past_259_stays(zone: Path, windows: ScanContext) -> None:
    # [0017.6] 259 moves, 260 stays; the detail is the destination's length
    folder = folder_of(zone, 200, "Documents")
    fits = write(folder / named(folder, "Documents", DESTINATION, ".pdf", "a"), b"fits")
    past = write(folder / named(folder, "Documents", DESTINATION + 1, ".pdf", "b"), b"past")
    found = plan(folder, windows)
    assert moved(found) == [fits.name]
    assert stays(found) == [(past.name, StayReason.PATH_TOO_LONG, "260 > 259")]


def test_the_length_is_counted_in_utf16_code_units(zone: Path, windows: ScanContext) -> None:
    # [0017.6] an emoji is one character here and two for Windows
    folder = folder_of(zone, 200, "Documents")
    name = named(folder, "Documents", DESTINATION, ".pdf", "\N{GRINNING FACE}")
    write(folder / name, b"wide")
    assert len(str(folder / "Documents" / name)) == DESTINATION
    assert stays(plan(folder, windows)) == [(name, StayReason.PATH_TOO_LONG, "260 > 259")]


def test_the_length_is_decided_before_the_system_is_asked(
    zone: Path, windows: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0017.6] a category path that cannot be looked at, a destination that cannot either:
    # neither is asked of a file that stays for its length
    folder = folder_of(zone, DIRECTORY + 1, "Documents")
    write(folder / "b.pdf", b"b.pdf")
    name = named(folder, "Images", DESTINATION + 1, ".jpg")
    write(folder / name, b"jpg")
    deny_stat(monkeypatch, folder / "Documents")
    deny_stat(monkeypatch, folder / "Images" / name)
    found = plan(folder, windows)
    assert [(n, reason) for n, reason, _ in stays(found)] == [
        ("b.pdf", StayReason.PATH_TOO_LONG),
        (name, StayReason.PATH_TOO_LONG),
    ]


def test_linux_and_macos_keep_no_file_for_its_length(zone: Path, scan: ScanContext) -> None:
    # [0017.6]
    folder = folder_of(zone, DIRECTORY + 1, "Documents")
    write(folder / "b.pdf", b"b.pdf")
    for platform in ("linux", "darwin"):
        found = plan(folder, dataclasses.replace(scan, platform=platform))
        assert (moved(found), found.stays) == (["b.pdf"], ())


def test_a_companion_of_a_file_that_stays_for_its_length_stays_too(
    zone: Path, windows: ScanContext
) -> None:
    # [0017.7] the same stem: .jpeg, one character longer than .jpg, passes the limit
    folder = folder_of(zone, 200, "Images")
    long = write(folder / named(folder, "Images", DESTINATION + 1, ".jpeg"), b"jpeg")
    short = write(folder / (long.name.removesuffix(".jpeg") + ".jpg"), b"jpg")
    found = plan(folder, windows)
    assert moved(found) == []
    assert [(n, reason) for n, reason, _ in stays(found)] == [
        (short.name, StayReason.COMPANION),
        (long.name, StayReason.PATH_TOO_LONG),
    ]


def test_the_window_names_it_in_english_and_russian() -> None:
    # [0017.7]
    reason = StayReason("path_too_long")
    assert Translator("en").label(reason) == "Its new path would be too long"
    assert Translator("ru").label(reason) == "Новый путь был бы слишком длинным"
