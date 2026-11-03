"""The folder organize sorts (decision 0012, items 7 and 8): a real directory the policy allows,
neither the home directory nor above it, that can be listed, and none whose files break when
moved. A refused folder is refused as a whole, before anything is planned.

The markers of item 8 are data (``organize/folders.toml``), and each has an example here, as
each junk rule and each extension has one. They are compared folded, as the names of item 20:
a wrong match only refuses a folder, a missed one breaks what is in it.
"""

import re
from pathlib import Path

import pytest

from fakes import deny_listing, deny_stat
from kresorter.core.scanner import ScanContext
from kresorter.organize.folders import (
    FolderMarkers,
    FolderReason,
    FolderRefused,
    default_markers,
    load_markers,
)
from kresorter.organize.planner import plan
from support.files import write

DECISION = Path(__file__).resolve().parents[2] / "docs" / "decisions" / "0012-organize.md"


def refusal(folder: Path, context: ScanContext) -> tuple[FolderReason, str]:
    with pytest.raises(FolderRefused) as refused:
        plan(folder, context)
    assert refused.value.folder == folder
    return refused.value.reason, refused.value.detail


def make(zone: Path, relative: str) -> Path:
    """``zone/relative``: a directory when it ends with ``/``, else a file."""
    path = zone / relative
    if relative.endswith("/"):
        path.mkdir(parents=True)
        return path
    return write(path)


# --- a real directory the policy allows and the user can list (item 7) -------------------------


def test_a_folder_below_the_home_directory_is_sorted(tmp_path: Path, scan: ScanContext) -> None:
    # [0012.7] the home of ``scan`` is tmp_path/users/me
    folder = tmp_path / "users" / "me" / "Downloads"
    write(folder / "report.pdf")
    assert [move.category for move in plan(folder, scan).moves] == ["Documents"]


def test_a_missing_folder_is_refused(zone: Path, scan: ScanContext) -> None:
    # [0012.7]
    assert refusal(zone / "Downloads", scan) == (FolderReason.NOT_FOUND, "")


def test_a_folder_below_a_file_is_refused_as_missing(zone: Path, scan: ScanContext) -> None:
    # [0012.7]
    assert refusal(write(zone / "notes.txt") / "Downloads", scan) == (FolderReason.NOT_FOUND, "")


def test_a_file_is_not_a_folder(zone: Path, scan: ScanContext) -> None:
    # [0012.7]
    assert refusal(write(zone / "notes.txt"), scan) == (FolderReason.NOT_A_DIRECTORY, "")


def test_a_link_is_refused_even_to_a_directory(zone: Path, scan: ScanContext) -> None:
    # [0012.7] the detail is where the link leads
    (zone / "real").mkdir()
    (zone / "Downloads").symlink_to(zone / "real")
    assert refusal(zone / "Downloads", scan) == (FolderReason.LINK, str(zone / "real"))


def test_a_folder_below_a_link_is_refused(zone: Path, scan: ScanContext) -> None:
    # [0012.7] a link anywhere above: the folder is not where its path says
    (zone / "real" / "Downloads").mkdir(parents=True)
    (zone / "via").symlink_to(zone / "real")
    folder = zone / "via" / "Downloads"
    assert refusal(folder, scan) == (FolderReason.LINK, str(zone / "real" / "Downloads"))


def test_a_folder_the_policy_blocks_is_refused(tmp_path: Path, scan: ScanContext) -> None:
    # [0012.7] ``scan`` blocks tmp_path/system as a system path
    folder = tmp_path / "system" / "Downloads"
    folder.mkdir(parents=True)
    assert refusal(folder, scan) == (FolderReason.BLOCKED, "system")


@pytest.mark.parametrize("below", ["", "vault"])
def test_the_data_directory_is_refused(data_dir: Path, scan: ScanContext, below: str) -> None:
    # [0012.7] the journal and the vault are kresorter's, whatever the folder holds
    folder = data_dir / below
    folder.mkdir(parents=True)
    assert refusal(folder, scan) == (FolderReason.BLOCKED, "app_data")


@pytest.mark.parametrize("above", [0, 1, 2])
def test_the_home_directory_and_above_it_are_refused(
    tmp_path: Path, scan: ScanContext, above: int
) -> None:
    # [0012.7] the home of ``scan``, then users, then tmp_path: their top level is not a mess
    home = tmp_path / "users" / "me"
    write(home / "notes.txt")
    folder = [home, *home.parents][above]
    assert refusal(folder, scan) == (FolderReason.HOME, "")


def test_a_folder_that_cannot_be_looked_at_is_refused(
    zone: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.7]
    folder = zone / "Downloads"
    folder.mkdir()
    deny_stat(monkeypatch, folder)
    assert refusal(folder, scan) == (FolderReason.UNREADABLE, "Permission denied")


def test_a_folder_that_cannot_be_listed_is_refused(
    zone: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.7]
    folder = zone / "Downloads"
    folder.mkdir()
    deny_listing(monkeypatch, folder)
    assert refusal(folder, scan) == (FolderReason.UNREADABLE, "Permission denied")


def test_an_entry_that_cannot_be_looked_at_refuses_the_folder(
    zone: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.7] listing the folder includes what each entry is
    folder = zone / "Downloads"
    write(folder / "a.jpg")
    deny_stat(monkeypatch, folder / "a.jpg")
    assert refusal(folder, scan) == (FolderReason.UNREADABLE, "a.jpg: Permission denied")


def test_the_folder_reasons_are_pinned() -> None:
    # [0012.7] those of item 8 last; adding or removing one is a decision of its own
    assert [reason.value for reason in FolderReason] == [
        "not_found",
        "not_a_directory",
        "link",
        "blocked",
        "home",
        "unreadable",
        "game_library",
        "project",
        "cache_or_temp",
    ]


def test_a_relative_folder_is_a_programming_error(scan: ScanContext) -> None:
    # the command line makes the folder absolute before planning
    with pytest.raises(ValueError, match="absolute"):
        plan(Path("Downloads"), scan)


# --- folders whose files break when moved (item 8) ---------------------------------------------

# The folder, below zone; what is made in it or above it, below zone (a directory when it ends
# with "/"); the reason, and the marker that refuses it.
MARKER_EXAMPLES: list[tuple[str, str, FolderReason, str]] = [
    ("steamapps/common/Game", "steamapps/common/Game/", FolderReason.GAME_LIBRARY, "steamapps"),
    ("Games/SteamLibrary", "Games/SteamLibrary/", FolderReason.GAME_LIBRARY, "SteamLibrary"),
    ("GOG Games/Witcher", "GOG Games/Witcher/", FolderReason.GAME_LIBRARY, "GOG Games"),
    ("Epic Games/Fortnite", "Epic Games/Fortnite/", FolderReason.GAME_LIBRARY, "Epic Games"),
    ("Steam", "Steam/libraryfolders.vdf", FolderReason.GAME_LIBRARY, "libraryfolders.vdf"),
    ("app", "app/.git/", FolderReason.PROJECT, ".git"),
    ("app/docs", "app/.hg/", FolderReason.PROJECT, ".hg"),  # in a parent
    ("old/src/assets", "old/.svn/", FolderReason.PROJECT, ".svn"),  # higher up
    ("app", "app/pyproject.toml", FolderReason.PROJECT, "pyproject.toml"),
    ("app", "app/setup.py", FolderReason.PROJECT, "setup.py"),
    ("app", "app/package.json", FolderReason.PROJECT, "package.json"),
    ("app", "app/Cargo.toml", FolderReason.PROJECT, "Cargo.toml"),
    ("app", "app/go.mod", FolderReason.PROJECT, "go.mod"),
    ("app", "app/CMakeLists.txt", FolderReason.PROJECT, "CMakeLists.txt"),
    ("app", "app/Makefile", FolderReason.PROJECT, "Makefile"),
    ("app", "app/meson.build", FolderReason.PROJECT, "meson.build"),
    ("app", "app/pom.xml", FolderReason.PROJECT, "pom.xml"),
    ("app", "app/build.gradle", FolderReason.PROJECT, "build.gradle"),
    ("app", "app/build.gradle.kts", FolderReason.PROJECT, "build.gradle.kts"),
    ("app", "app/Gemfile", FolderReason.PROJECT, "Gemfile"),
    ("app", "app/composer.json", FolderReason.PROJECT, "composer.json"),
    ("app", "app/App.sln", FolderReason.PROJECT, "*.sln"),
    ("app", "app/App.csproj", FolderReason.PROJECT, "*.csproj"),
    ("app", "app/App.xcodeproj/", FolderReason.PROJECT, "*.xcodeproj"),
    # Folded, as the names of item 20.
    ("Steam/SteamApps/common", "Steam/SteamApps/common/", FolderReason.GAME_LIBRARY, "steamapps"),
    ("app", "app/makefile", FolderReason.PROJECT, "Makefile"),
    ("app", "app/APP.SLN", FolderReason.PROJECT, "*.sln"),
]


@pytest.mark.parametrize(("folder", "made", "reason", "marker"), MARKER_EXAMPLES)
def test_a_folder_a_marker_names_is_refused_as_a_whole(
    zone: Path, scan: ScanContext, folder: str, made: str, reason: FolderReason, marker: str
) -> None:
    # [0012.8]
    make(zone, made)
    (zone / folder).mkdir(parents=True, exist_ok=True)
    write(zone / folder / "report.pdf")
    assert refusal(zone / folder, scan) == (reason, marker)


def every_marker() -> set[str]:
    markers = default_markers()
    return {
        *markers.game_path_names,
        *markers.game_files,
        *markers.version_control,
        *markers.project_files,
    }


def test_every_marker_has_an_example() -> None:
    # [0012.8]
    assert every_marker() <= {marker for *_, marker in MARKER_EXAMPLES}


def test_the_markers_include_every_one_the_decision_names() -> None:
    # [0012.8] the decision names some build files, then "..."
    text = DECISION.read_text(encoding="utf-8")
    item = text[text.index("\n8. **") : text.index("\n9. **")]
    named = set(re.findall(r"`([^`]+)`", item))
    assert "Makefile" in named
    assert sorted(named - every_marker()) == []


@pytest.mark.parametrize(
    ("folder", "rule"),
    [
        (".cache/thumbnails", "user-cache-dir"),
        ("app/__pycache__", "python-bytecode"),
        ("app/.pytest_cache", "tool-caches"),
    ],
)
def test_a_cache_or_temp_directory_is_refused(
    zone: Path, scan: ScanContext, folder: str, rule: str
) -> None:
    # [0012.8] the directories of a junk rule match the folder; the junk rules have their examples
    write(zone / folder / "a.jpg")
    assert refusal(zone / folder, scan) == (FolderReason.CACHE_OR_TEMP, rule)


def test_markers_one_level_down_refuse_nothing(zone: Path, scan: ScanContext) -> None:
    # [0012.8] a project or a game in a subdirectory is a unit that stays (item 2)
    folder = zone / "Downloads"
    for relative in ("app/.git/HEAD", "app/Makefile", "game/libraryfolders.vdf", "a.jpg"):
        write(folder / relative)
    assert [move.source.name for move in plan(folder, scan).moves] == ["a.jpg"]


# --- the markers, as data ----------------------------------------------------------------------

VALID = """
[game_library]
path_names = ["steamapps"]
files = ["libraryfolders.vdf"]

[project]
version_control = [".git"]
files = ["Makefile", "*.sln"]
"""


def test_markers_are_read_from_their_text() -> None:
    assert load_markers(VALID) == FolderMarkers(
        game_path_names=("steamapps",),
        game_files=("libraryfolders.vdf",),
        version_control=(".git",),
        project_files=("Makefile", "*.sln"),
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "[game_library]\npath_names = []\nfiles = []\n",
            r"tables \[game_library\] and \[project\]",
        ),
        (VALID + "[other]\n", r"tables \[game_library\] and \[project\]"),
        (
            VALID.replace('files = ["libraryfolders.vdf"]', ""),
            r"\[game_library\]: path_names, files",
        ),
        (VALID + 'project.extra = ["x"]\n', r"\[project\]: version_control, files"),
        ("game_library = 1\n" + VALID[VALID.index("[project]") :], r"\[game_library\]: path_names"),
        (VALID.replace('[".git"]', '".git"'), r"\[project\] version_control: a list of names"),
        (VALID.replace('"*.sln"', "1"), r"\[project\] files: a list of names"),
        (VALID.replace('"*.sln"', '""'), r"\[project\] files: a list of names"),
    ],
)
def test_invalid_markers_are_rejected(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_markers(text)
