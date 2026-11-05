"""`kresorter organize` on macOS, on Linux and Windows without a reliable open-file check, on
Windows with one, and folded names end to end (decision 0012, items 20, 37-39; 0017, items 1
and 12).

On a blocked system `move` and `undo` refuse before anything, with or without `--yes`: before
the journal is opened (the data directory is not made), before planning, and without asking
the open-file check. On macOS the checker is the one kresorter gives that system today, or a
reliable fake: a backend alone does not lift the refusal (item 39); on Linux and Windows an
unreliable checker is the one blocker, and with a reliable one Windows sorts as Linux does.
`list` and `recover` move nothing and run everywhere. The platform is the one the scan context
was made for (`ScanContext.platform`, required); real temporary trees.
"""

import dataclasses
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from fakes import FakeOpenFiles, UnreliableOpenFiles
from kresorter import environment
from kresorter.core.heuristics import Platform
from kresorter.core.open_files import NoOpenFileCheck
from kresorter.core.scanner import ScanContext
from kresorter.organize.platforms import refusal
from support.cli import autostart_context, run, scan_context
from support.files import snapshot, write
from support.host import alias
from support.journal import query
from support.moves import B, crash, planned, three_files, tree

BLOCKED = pytest.mark.parametrize("platform", ["darwin", "windows"])  # without a reliable check
UNCHECKED = pytest.mark.parametrize(
    ("platform", "name"), [("linux", "Linux"), ("windows", "Windows")]
)
ACTING = pytest.mark.parametrize(
    "action",
    [["move", "FOLDER"], ["move", "FOLDER", "--yes"], ["undo", "1"], ["undo", "1", "--yes"]],
    ids=["move", "move-yes", "undo", "undo-yes"],
)
NFC = "caf\u00e9"
NFD = "cafe\u0301"


def downloads(zone: Path, *names: str) -> Path:
    folder = zone / "Downloads"
    folder.mkdir()
    for name in names or ("report.pdf", "photo.jpg"):
        write(folder / name)
    return folder


def organize(action: list[str], folder: Path) -> list[str]:
    return ["organize", *(str(folder) if arg == "FOLDER" else arg for arg in action)]


def everything(root: Path) -> tuple[list[str], list[tuple[str, int, int, bytes]]]:
    """Every path under ``root``, directories included, and what every file holds."""
    return sorted(str(p) for p in root.rglob("*")), snapshot(root)


# --- move and undo refuse on macOS and Windows -------------------------------------------------


@ACTING
@pytest.mark.parametrize(
    ("platform", "reliable"),
    [("darwin", False), ("darwin", True), ("windows", False)],
    ids=["macos-today", "macos-with-a-backend", "windows-unchecked"],
)
def test_move_and_undo_refuse_before_anything(
    platform: Platform,
    action: list[str],
    reliable: bool,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
) -> None:
    # [0012.37] [0012.39] [0017.1] no plan, no journal, no category directory, the message of
    # item 38
    folder = downloads(zone)
    open_files = FakeOpenFiles() if reliable else NoOpenFileCheck()
    context = scan_context(tmp_path, zone, data_dir, open_files, platform=platform)
    before = everything(tmp_path)
    code, out, err = run(organize(action, folder), context)
    assert (code, out, err) == (3, "", refusal(platform, open_files))
    assert everything(tmp_path) == before
    assert not data_dir.exists()


@ACTING
def test_the_open_file_check_is_never_asked(
    action: list[str], tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.37] the refusal is not a preflight: it comes first, on macOS whatever its check
    folder = downloads(zone)
    open_files = FakeOpenFiles([folder / "report.pdf"])
    run(
        organize(action, folder),
        scan_context(tmp_path, zone, data_dir, open_files, platform="darwin"),
    )
    assert open_files.calls == []


def test_macos_today_is_told_both_of_its_blockers(
    tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.37] [0012.38] the message as the user reads it
    folder = downloads(zone)
    context = scan_context(tmp_path, zone, data_dir, NoOpenFileCheck(), platform="darwin")
    code, _, err = run(["organize", "move", str(folder), "--yes"], context)
    assert code == 3
    assert err == (
        "kresorter: organize does not move files on macOS; nothing was changed\n"
        "  - no reliable open-file check: a file a program holds open could be moved"
        " from under it\n"
        "  - Desktop and Documents can be synced to the cloud: a move would reach every device\n"
    )


@BLOCKED
def test_usage_errors_come_first(
    platform: Platform, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.36] 2 before 3: undo without a batch is a usage error everywhere
    context = scan_context(tmp_path, zone, data_dir, NoOpenFileCheck(), platform=platform)
    with pytest.raises(SystemExit) as raised:
        run(["organize", "undo"], context)
    assert raised.value.code == 2


# --- Linux without a reliable open-file check, and the platform of the context -----------------


@UNCHECKED
@ACTING
def test_without_a_reliable_check_linux_and_windows_refuse_before_anything(
    platform: Platform, name: str, action: list[str], tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.36] [0012.37] [0012.38] [0012.39] [0017.1] [0017.2] the open-file check's line
    # alone; nothing changed
    folder = downloads(zone)
    context = scan_context(tmp_path, zone, data_dir, NoOpenFileCheck(), platform=platform)
    before = everything(tmp_path)
    assert run(organize(action, folder), context) == (
        3,
        "",
        f"kresorter: organize does not move files on {name}; nothing was changed\n"
        "  - no reliable open-file check: a file a program holds open could be moved"
        " from under it\n",
    )
    assert everything(tmp_path) == before
    assert not data_dir.exists()


@UNCHECKED
@ACTING
def test_without_a_reliable_check_linux_and_windows_never_ask_it(
    platform: Platform, name: str, action: list[str], tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.37] [0017.1] the refusal is not a preflight: it comes first
    folder = downloads(zone)
    unreliable = UnreliableOpenFiles([folder / "report.pdf"])
    context = scan_context(tmp_path, zone, data_dir, unreliable, platform=platform)
    run(organize(action, folder), context)
    assert unreliable.calls == []


# --- Windows sorts with a reliable check (decision 0017, items 1 and 12) ------------------------


def test_windows_with_a_reliable_check_moves_and_undoes(
    tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0017.1] as on Linux: the batch, then its undo, every file back where it was
    folder = three_files(zone)
    before = tree(zone)
    windows = scan_context(tmp_path, zone, data_dir, platform="windows")
    code, out, err = run(["organize", "move", str(folder), "--yes"], windows)
    assert (code, err) == (0, "")
    assert out.startswith(f"Moved 3 files, 15 B, in {folder} (batch 1):\n")
    assert sorted(p.name for p in folder.iterdir()) == ["Audio", "Documents", "Images"]
    code, out, err = run(["organize", "undo", "1", "--yes"], windows)
    assert (code, err) == (0, "")
    made = {f"Downloads/{category}": "dir" for category in ("Audio", "Documents", "Images")}
    assert tree(zone) == {**before, **made}


def test_on_windows_a_folder_given_in_another_case_is_sorted_as_the_system_spells_it(
    tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0017.12] the plan, the batch and the journal take the system's spelling; where the
    # system tells case apart a link from the other case stands for it
    real = three_files(zone / "Ann")
    alias(zone / "ann", zone / "Ann")
    given = zone / "ann" / "Downloads"
    windows = scan_context(tmp_path, zone, data_dir, platform="windows")
    code, out, _ = run(["organize", "move", str(given)], windows)
    assert (code, out.splitlines()[0]) == (1, f"Would move 3 files, 15 B, in {real}:")
    code, out, _ = run(["organize", "move", str(given), "--yes"], windows)
    assert (code, out.splitlines()[0]) == (0, f"Moved 3 files, 15 B, in {real} (batch 1):")
    assert query(data_dir, "SELECT folder FROM move_batches") == [(str(real),)]
    assert sorted(p.name for p in real.iterdir()) == ["Audio", "Documents", "Images"]


def test_list_and_recover_run_on_linux_without_a_reliable_check(
    tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.37] neither moves a file, and recovery needs no open-file check
    folder = three_files(zone)
    data_dir.mkdir(mode=0o700, parents=True)
    crash(data_dir / "journal.db", folder, planned(folder), {folder / B: "exit-after"})
    unchecked = scan_context(tmp_path, zone, data_dir, NoOpenFileCheck())
    before = tree(zone)

    code, out, err = run(["organize", "list"], unchecked)

    assert (code, err) == (0, "")
    assert out.startswith(
        "Recovered 1 interrupted organize batch:\n  [1] failed: 2 files still sorted;"
    )
    assert out.endswith("  2 files moved  failed  " + str(folder) + "\n")
    auto = autostart_context("linux", tmp_path)
    assert run(["recover"], unchecked, auto) == (0, "Nothing to recover.\n", "")
    assert tree(zone) == before


@pytest.mark.parametrize("platform", ["linux", "darwin", "windows"])
def test_a_scan_context_carries_the_platform_it_was_made_for(platform: Platform) -> None:
    # [0012.37] [0012.39] the refusal asks the context, not the system the tests run on
    env = {"USERPROFILE": r"C:\Users\Alice"}
    # [0015.20] a home as the context's system writes it, on Windows too
    context = environment.default_context(
        platform=platform, env=env, home=PurePosixPath("/home/alice")
    )
    assert context.platform == platform


def test_the_default_context_is_made_for_the_system_it_detects(tmp_path: Path) -> None:
    # [0012.39]
    env = {"USERPROFILE": r"C:\Users\Alice"}
    context = environment.default_context(env=env, home=tmp_path)
    assert context.platform == environment.detect_platform()


def test_a_scan_context_cannot_be_made_without_its_platform(scan: ScanContext) -> None:
    # [0012.39] no default: a context that does not say its system is not taken for Linux
    fields: dict[str, Any] = {
        field.name: getattr(scan, field.name)
        for field in dataclasses.fields(scan)
        if field.name != "platform"
    }
    with pytest.raises(TypeError, match="platform"):
        ScanContext(**fields)


def test_a_scan_context_cannot_be_made_without_its_synced_folders(scan: ScanContext) -> None:
    # [0017.10] a required field like platform: no context forgets to ask
    fields: dict[str, Any] = {
        field.name: getattr(scan, field.name)
        for field in dataclasses.fields(scan)
        if field.name != "synced"
    }
    with pytest.raises(TypeError, match="synced"):
        ScanContext(**fields)


# --- list and recover run everywhere -------------------------------------------------------------


@BLOCKED
def test_list_runs_everywhere(
    platform: Platform, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.34] [0012.37]
    context = scan_context(tmp_path, zone, data_dir, NoOpenFileCheck(), platform=platform)
    assert run(["organize", "list"], context) == (0, "No organize batches.\n", "")


@BLOCKED
def test_recover_runs_everywhere(
    platform: Platform, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.37] nothing to recover is not a refusal
    context = scan_context(tmp_path, zone, data_dir, NoOpenFileCheck(), platform=platform)
    auto = autostart_context(platform, tmp_path)
    assert run(["recover"], context, auto) == (0, "Nothing to recover.\n", "")


@BLOCKED
def test_recover_settles_an_interrupted_batch_everywhere(
    platform: Platform, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.31] [0012.37] a crash left a batch; recovery moves nothing, so nothing blocks it
    folder = three_files(zone)
    data_dir.mkdir(mode=0o700, parents=True)
    crash(data_dir / "journal.db", folder, planned(folder), {folder / B: "exit-after"})
    context = scan_context(tmp_path, zone, data_dir, NoOpenFileCheck(), platform=platform)
    before = tree(zone)
    code, _, _ = run(["recover"], context, autostart_context(platform, tmp_path))
    assert code == 0
    assert query(data_dir, "SELECT state FROM moves ORDER BY id") == [
        ("done",),
        ("done",),
        ("rolled_back",),
    ]
    assert query(data_dir, "SELECT state FROM move_batches") == [("failed",)]
    assert tree(zone) == before


# --- folded names end to end, on Linux (item 20) -----------------------------------------------


@pytest.mark.parametrize(
    "pair", [("Movie.mkv", "movie.nfo"), (f"{NFC}.jpg", f"{NFD}.xmp")], ids=["case", "unicode"]
)
def test_a_pair_stays_while_the_rest_moves(
    pair: tuple[str, str], zone: Path, scan: ScanContext
) -> None:
    # [0012.14] [0012.20] [0012.33] on Linux, with a reliable check: only the report moves
    folder = downloads(zone, *pair, "report.pdf")
    code, _, _ = run(["organize", "move", str(folder), "--yes"], scan)
    assert code == 0
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")) == sorted(
        [*pair, "Documents", "Documents/report.pdf"]
    )
