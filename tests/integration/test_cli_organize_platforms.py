"""`safeclean organize` on macOS and Windows, on Linux without a reliable open-file check, and
folded names end to end (decision 0012, items 20, 37-39).

On a blocked system `move` and `undo` refuse before anything, with or without `--yes`: before
the journal is opened (the data directory is not made), before planning, and without asking
the open-file check. On macOS and Windows the checker is the one safeclean gives that system
today, or a reliable fake: a backend alone does not lift the refusal (item 39); on Linux an
unreliable checker is the one blocker. `list` and `recover` move nothing and run everywhere.
The platform is the one the scan context was made for (`ScanContext.platform`, required);
real temporary trees.
"""

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from fakes import FakeOpenFiles, UnreliableOpenFiles
from safeclean import cli
from safeclean.core.heuristics import Platform
from safeclean.core.open_files import NoOpenFileCheck
from safeclean.core.scanner import ScanContext
from safeclean.organize.platforms import refusal
from support.cli import autostart_context, run, scan_context
from support.files import snapshot, write
from support.journal import query
from support.moves import B, crash, planned, three_files, tree

BLOCKED = pytest.mark.parametrize("platform", ["darwin", "windows"])
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


@BLOCKED
@ACTING
@pytest.mark.parametrize("reliable", [False, True], ids=["today", "with-a-backend"])
def test_move_and_undo_refuse_before_anything(
    platform: Platform,
    action: list[str],
    reliable: bool,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
) -> None:
    # [0012.37] [0012.39] no plan, no journal, no category directory, the message of item 38
    folder = downloads(zone)
    open_files = FakeOpenFiles() if reliable else NoOpenFileCheck()
    context = scan_context(tmp_path, zone, data_dir, open_files, platform=platform)
    before = everything(tmp_path)
    code, out, err = run(organize(action, folder), context)
    assert (code, out, err) == (3, "", refusal(platform, open_files))
    assert everything(tmp_path) == before
    assert not data_dir.exists()


@BLOCKED
@ACTING
def test_the_open_file_check_is_never_asked(
    platform: Platform, action: list[str], tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.37] the refusal is not a preflight: it comes first
    folder = downloads(zone)
    open_files = FakeOpenFiles([folder / "report.pdf"])
    run(
        organize(action, folder),
        scan_context(tmp_path, zone, data_dir, open_files, platform=platform),
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
        "safeclean: organize does not move files on macOS; nothing was changed\n"
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


@ACTING
def test_linux_without_a_reliable_check_refuses_before_anything(
    action: list[str], tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.36] [0012.37] [0012.38] [0012.39] the open-file check's line alone; nothing changed
    folder = downloads(zone)
    context = scan_context(tmp_path, zone, data_dir, NoOpenFileCheck())
    before = everything(tmp_path)
    assert run(organize(action, folder), context) == (
        3,
        "",
        "safeclean: organize does not move files on Linux; nothing was changed\n"
        "  - no reliable open-file check: a file a program holds open could be moved"
        " from under it\n",
    )
    assert everything(tmp_path) == before
    assert not data_dir.exists()


@ACTING
def test_linux_without_a_reliable_check_never_asks_it(
    action: list[str], tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.37] the refusal is not a preflight: it comes first
    folder = downloads(zone)
    unreliable = UnreliableOpenFiles([folder / "report.pdf"])
    run(organize(action, folder), scan_context(tmp_path, zone, data_dir, unreliable))
    assert unreliable.calls == []


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
def test_a_scan_context_carries_the_platform_it_was_made_for(
    tmp_path: Path, platform: Platform
) -> None:
    # [0012.37] [0012.39] the refusal asks the context, not the system the tests run on
    env = {"USERPROFILE": r"C:\Users\Alice"}
    assert cli.default_context(platform=platform, env=env, home=tmp_path).platform == platform


def test_the_default_context_is_made_for_the_system_it_detects(tmp_path: Path) -> None:
    # [0012.39]
    env = {"USERPROFILE": r"C:\Users\Alice"}
    context = cli.default_context(env=env, home=tmp_path)
    assert context.platform == cli.detect_platform()


def test_a_scan_context_cannot_be_made_without_its_platform(scan: ScanContext) -> None:
    # [0012.39] no default: a context that does not say its system is not taken for Linux
    fields: dict[str, Any] = {
        field.name: getattr(scan, field.name)
        for field in dataclasses.fields(scan)
        if field.name != "platform"
    }
    with pytest.raises(TypeError, match="platform"):
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
    "pair", [("Movie.mkv", "movie.srt"), (f"{NFC}.jpg", f"{NFD}.xmp")], ids=["case", "unicode"]
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
