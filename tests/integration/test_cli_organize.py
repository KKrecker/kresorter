"""``kresorter organize move | list | undo`` on Linux (decision 0012, items 1-5, 7, 29, 30 and
33-36).

Every command opens the journal and recovers organize's own batches first; ``move`` and
``undo`` then refuse while another domain's work is unfinished, and ``list`` runs. Without
``--yes`` the plan is shown and nothing is made, moved or journaled (exit 1); with it, the plan
is made again inside the lock, checked once more and carried out, and the output says exactly
what moved, what was refused and what stays. Real temporary trees, a reliable fake open-file
check; the platform's own refusals are in ``test_cli_organize_platforms.py``.
"""

import functools
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, other_device
from kresorter import cli_organize
from kresorter.core.scanner import ScanContext
from kresorter.organize.mover import carry_out
from support.cli import run, scan_context
from support.files import write
from support.journal import query
from support.moves import (
    MOVED,
    SOURCES,
    A,
    B,
    C,
    FlakyRename,
    content,
    crash,
    planned,
    three_files,
    tree,
)

SORTED = {A: MOVED[A], B: MOVED[B], C: MOVED[C]}
CATEGORIES = {"Audio": "dir", "Documents": "dir", "Images": "dir"}


def organize(*args: str | Path | int) -> list[str]:
    return ["organize", *(str(arg) for arg in args)]


def messy(zone: Path) -> Path:
    """``three_files``, with a subdirectory, the folder's metadata and junk beside them."""
    folder = three_files(zone)
    write(folder / "old" / "inside.jpg", b"inside")
    write(folder / ".hidden", b"hidden")
    write(folder / "old.tmp", b"old")
    return folder


def plan_of(folder: Path) -> str:
    """The plan of ``messy``, as ``organize move`` shows it."""
    return (
        f"Would move 3 files, 15 B, in {folder}:\n"
        "  Images: 1 file, 5 B\n"
        "    a.jpg -> Images/\n"
        "  Audio: 1 file, 5 B\n"
        "    c.mp3 -> Audio/\n"
        "  Documents: 1 file, 5 B\n"
        "    b.pdf -> Documents/\n"
        "Stays 3:\n"
        "  not_regular: old\n"
        "  folder_metadata: .hidden\n"
        "  junk: old.tmp (temp-files)\n"
        "Nothing was moved. Re-run with --yes to move these files.\n"
    )


def sorted_by_cli(scan: ScanContext, folder: Path) -> None:
    """``organize move FOLDER --yes``: batch 1."""
    assert run(organize("move", folder, "--yes"), scan)[0] == 0


def created(data_dir: Path, batch: int) -> str:
    ((ns,),) = query(data_dir, "SELECT created_at_ns FROM move_batches WHERE id = ?", batch)
    assert isinstance(ns, int)
    return datetime.fromtimestamp(ns // 1_000_000_000, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def quarantine_left_pending(scan: ScanContext, zone: Path, data_dir: Path) -> None:
    """The quarantine's work as a crash right after its move would leave it."""
    assert run(["quarantine", "add", str(write(zone / "q.bin"))], scan)[0] == 0
    query(data_dir, "UPDATE items SET state = 'pending'")
    query(data_dir, "UPDATE operations SET state = 'pending', finished_at_ns = NULL")


# --- organize move, the plan --------------------------------------------------------------------


def test_without_yes_the_plan_is_shown_and_nothing_changes(
    scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.1] [0012.2] [0012.5] [0012.33] [0012.36] the journal is opened, nothing is journaled
    folder = messy(zone)
    before = tree(zone)

    code, out, err = run(organize("move", folder), scan)

    assert (code, out, err) == (1, plan_of(folder), "")
    assert tree(zone) == before
    assert query(data_dir, "SELECT COUNT(*) FROM move_batches") == [(0,)]


def test_the_plan_comes_after_recovering_organize(
    scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.1] [0012.33] a crashed batch is closed first; its category directories stay, Audio
    # included: made before the crash, before c could move
    data_dir.mkdir(parents=True)
    folder = three_files(zone)
    crash(data_dir / "journal.db", folder, planned(folder), {folder / C: "exit-before"})

    code, out, _ = run(organize("move", folder), scan)

    assert code == 1
    assert out == (
        "Recovered 1 interrupted organize batch:\n"
        "  [1] failed: 2 files still sorted; 'kresorter organize undo 1' moves them back\n"
        f"    {folder / MOVED[A]}\n"
        f"    {folder / MOVED[B]}\n"
        f"Would move 1 file, 5 B, in {folder}:\n"
        "  Audio: 1 file, 5 B\n"
        "    c.mp3 -> Audio/\n"
        "Stays 3:\n"
        "  not_regular: Audio\n"
        "  not_regular: Documents\n"
        "  not_regular: Images\n"
        "Nothing was moved. Re-run with --yes to move these files.\n"
    )


@pytest.mark.parametrize("yes", [[], ["--yes"]], ids=["plan", "yes"])
def test_nothing_to_move(scan: ScanContext, zone: Path, data_dir: Path, yes: list[str]) -> None:
    # [0012.5] [0012.36] what stays is still said
    folder = zone / "Downloads"
    write(folder / ".hidden")

    code, out, _ = run(organize("move", folder, *yes), scan)

    assert (code, out) == (
        1,
        f"Nothing to move in {folder}.\nStays 1:\n  folder_metadata: .hidden\n",
    )
    assert query(data_dir, "SELECT COUNT(*) FROM move_batches") == [(0,)]


@pytest.mark.parametrize("yes", [[], ["--yes"]], ids=["plan", "yes"])
def test_a_refused_folder_plans_nothing(
    scan: ScanContext, zone: Path, data_dir: Path, yes: list[str]
) -> None:
    # [0012.7] [0012.8] [0012.36] the reason, and the marker when there is one
    project = three_files(zone)
    write(project / "Makefile")
    missing = zone / "nowhere"

    assert run(organize("move", project, *yes), scan) == (
        1,
        f"Refused: {project}: project (Makefile)\n",
        "",
    )
    assert run(organize("move", missing, *yes), scan) == (1, f"Refused: {missing}: not_found\n", "")
    assert files_of(project) == {**content(SOURCES), "Makefile": b"payload"}
    assert query(data_dir, "SELECT COUNT(*) FROM move_batches") == [(0,)]


def files_of(folder: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in folder.iterdir()}


def test_a_relative_folder_is_taken_from_the_working_directory(
    scan: ScanContext, zone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.33] and named as an absolute path
    folder = messy(zone)
    monkeypatch.chdir(zone)

    assert run(organize("move", "Downloads"), scan) == (1, plan_of(folder), "")


# --- organize move --yes -----------------------------------------------------------------------


def test_yes_moves_and_says_what_moved(scan: ScanContext, zone: Path, data_dir: Path) -> None:
    # [0012.2] [0012.3] [0012.33] [0012.36] one category directory below, the same names
    folder = messy(zone)

    code, out, err = run(organize("move", folder, "--yes"), scan)

    assert (code, err) == (0, "")
    assert out == (
        f"Moved 3 files, 15 B, in {folder} (batch 1):\n"
        "  Images: 1 file, 5 B\n"
        "    a.jpg -> Images/\n"
        "  Audio: 1 file, 5 B\n"
        "    c.mp3 -> Audio/\n"
        "  Documents: 1 file, 5 B\n"
        "    b.pdf -> Documents/\n"
        "Stays 3:\n"
        "  not_regular: old\n"
        "  folder_metadata: .hidden\n"
        "  junk: old.tmp (temp-files)\n"
        "'kresorter organize undo 1' moves them back\n"
    )
    assert tree(folder) == {
        **content(SORTED),
        **CATEGORIES,
        "old": "dir",
        "old/inside.jpg": b"inside",
        ".hidden": b"hidden",
        "old.tmp": b"old",
    }
    assert query(data_dir, "SELECT kind, state FROM move_batches") == [("organize", "done")]


def test_one_file_moved_says_it_moves_back(scan: ScanContext, zone: Path) -> None:
    # [0012.33]
    folder = zone / "Downloads"
    write(folder / A, A.encode())

    code, out, err = run(organize("move", folder, "--yes"), scan)

    assert (code, err) == (0, "")
    assert out == (
        f"Moved 1 file, 5 B, in {folder} (batch 1):\n"
        "  Images: 1 file, 5 B\n"
        f"    {A} -> Images/\n"
        "'kresorter organize undo 1' moves it back\n"
    )


def test_the_plan_is_made_again_at_move_time(scan: ScanContext, zone: Path) -> None:
    # [0012.33] the plan shown is not trusted: a file added since is planned and moves too
    folder = three_files(zone)
    run(organize("move", folder), scan)
    write(folder / "d.png", b"d.png")

    code, out, _ = run(organize("move", folder, "--yes"), scan)

    assert code == 0
    assert out.startswith(
        f"Moved 4 files, 20 B, in {folder} (batch 1):\n"
        "  Images: 2 files, 10 B\n"
        "    a.jpg -> Images/\n"
        "    d.png -> Images/\n"
    )
    assert (folder / "Images" / "d.png").read_bytes() == b"d.png"


def test_a_taken_destination_is_never_overwritten(scan: ScanContext, zone: Path) -> None:
    # [0012.4] [0012.36] the file stays, by the plan: not a refusal, the rest moves
    folder = three_files(zone)
    write(folder / MOVED[A], b"already there")

    code, out, _ = run(organize("move", folder, "--yes"), scan)

    assert (code, out) == (
        0,
        f"Moved 2 files, 10 B, in {folder} (batch 1):\n"
        "  Audio: 1 file, 5 B\n"
        "    c.mp3 -> Audio/\n"
        "  Documents: 1 file, 5 B\n"
        "    b.pdf -> Documents/\n"
        "Stays 2:\n"
        "  not_regular: Images\n"
        "  conflict: a.jpg\n"
        "'kresorter organize undo 1' moves them back\n",
    )
    assert tree(folder) == {
        A: A.encode(),
        MOVED[A]: b"already there",
        MOVED[B]: B.encode(),
        MOVED[C]: C.encode(),
        **CATEGORIES,
    }


def test_a_file_refused_at_move_time_stays_and_the_rest_moves(
    tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0012.33] [0012.36] preflight is the last word
    folder = three_files(zone)
    held = scan_context(tmp_path, zone, data_dir, FakeOpenFiles([folder / B]))

    code, out, _ = run(organize("move", folder, "--yes"), held)

    assert (code, out) == (
        1,
        f"Moved 2 files, 10 B, in {folder} (batch 1):\n"
        "  Images: 1 file, 5 B\n"
        "    a.jpg -> Images/\n"
        "  Audio: 1 file, 5 B\n"
        "    c.mp3 -> Audio/\n"
        "Refused 1:\n"
        f"  open_file: {folder / B}\n"
        "'kresorter organize undo 1' moves them back\n",
    )
    assert tree(folder) == {
        **content({A: MOVED[A], B: B, C: MOVED[C]}),
        "Audio": "dir",
        "Images": "dir",
    }


def test_every_file_refused_means_no_batch(tmp_path: Path, zone: Path, data_dir: Path) -> None:
    # [0012.33] [0012.36]
    folder = three_files(zone)
    held = scan_context(tmp_path, zone, data_dir, FakeOpenFiles(folder / n for n in (A, B, C)))

    code, out, _ = run(organize("move", folder, "--yes"), held)

    assert (code, out) == (
        1,
        f"Nothing was moved in {folder}.\n"
        "Refused 3:\n"
        f"  open_file: {folder / A}\n"
        f"  open_file: {folder / C}\n"
        f"  open_file: {folder / B}\n",
    )
    assert tree(folder) == content(SOURCES)
    assert query(data_dir, "SELECT COUNT(*) FROM move_batches") == [(0,)]


def test_a_batch_that_stopped_exits_3(
    scan: ScanContext, zone: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.36] Images, made by the batch, turns out to be on another device: nothing is left
    folder = three_files(zone)
    other_device(monkeypatch, folder / "Images")

    code, out, _ = run(organize("move", folder, "--yes"), scan)

    assert (code, out) == (
        3,
        f"Stopped: [Errno 18] on another device than the folder: '{folder / 'Images'}'\n"
        "  [1] rolled_back\n",
    )
    assert tree(folder) == {**content(SOURCES), "Images": "dir"}
    assert query(data_dir, "SELECT state FROM move_batches") == [("rolled_back",)]


def test_a_batch_that_stopped_names_the_files_still_sorted(
    scan: ScanContext, zone: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.33] [0012.36] c cannot move and a new a.jpg took a's place: a stays sorted, named
    folder = three_files(zone)

    def newcomer() -> None:
        write(folder / A, b"newcomer")

    rename = FlakyRename({folder / C: "before"}, meanwhile={folder / C: newcomer})
    monkeypatch.setattr(cli_organize, "carry_out", functools.partial(carry_out, rename=rename))

    code, out, _ = run(organize("move", folder, "--yes"), scan)

    assert (code, out) == (
        3,
        f"Stopped: [Errno 13] refused before the move: '{folder / C}'\n"
        "  [1] failed: 1 file still sorted; 'kresorter organize undo 1' moves it back\n"
        f"    {folder / MOVED[A]}\n",
    )
    assert query(data_dir, "SELECT state FROM move_batches") == [("failed",)]


def test_another_domain_unfinished_refuses_move_and_undo(
    scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.36] with or without --yes; nothing was changed
    folder = three_files(zone)
    quarantine_left_pending(scan, zone, data_dir)
    refused = (
        3,
        "",
        "kresorter: the journal has unfinished quarantine work; run 'kresorter recover' first;"
        " nothing was changed\n",
    )

    for action in (["move", str(folder)], ["move", str(folder), "--yes"], ["undo", "1"]):
        assert run(organize(*action), scan) == refused
    assert run(organize("undo", 1, "--yes"), scan) == refused
    assert tree(folder) == content(SOURCES)


def test_a_data_directory_that_cannot_be_used_exits_3(
    scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.36] before planning
    folder = three_files(zone)
    write(data_dir, b"not a directory")

    code, out, err = run(organize("move", folder, "--yes"), scan)

    assert (code, out) == (3, "")
    assert err.startswith("kresorter: cannot use the data directory: ")
    assert tree(folder) == content(SOURCES)


@pytest.mark.parametrize(
    "args",
    [[], ["move"], ["undo"], ["undo", "one"], ["list", "extra"], ["move", "a", "b"]],
    ids=["no-action", "move-nothing", "undo-nothing", "undo-not-a-number", "list-extra", "two"],
)
def test_usage_errors_exit_2(scan: ScanContext, args: list[str]) -> None:
    # [0012.36]
    with pytest.raises(SystemExit) as raised:
        run(organize(*args), scan)
    assert raised.value.code == 2


# --- organize undo -----------------------------------------------------------------------------


def test_undo_without_yes_shows_the_plan(scan: ScanContext, zone: Path, data_dir: Path) -> None:
    # [0012.29] [0012.35] [0012.36] in journal order; nothing changes
    folder = three_files(zone)
    sorted_by_cli(scan, folder)
    before = tree(zone)

    code, out, err = run(organize("undo", 1), scan)

    assert (code, err) == (1, "")
    assert out == (
        f"Would move back 3 files, 15 B, sorted by batch 1 in {folder}:\n"
        "  Images/a.jpg -> a.jpg\n"
        "  Audio/c.mp3 -> c.mp3\n"
        "  Documents/b.pdf -> b.pdf\n"
        "Nothing was moved. Re-run with --yes to move these files back.\n"
    )
    assert tree(zone) == before
    assert query(data_dir, "SELECT COUNT(*) FROM move_batches") == [(1,)]


def test_undo_with_yes_moves_back_and_leaves_the_directories(
    scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.4] [0012.29] [0012.35] [0012.36] a batch of its own
    folder = three_files(zone)
    sorted_by_cli(scan, folder)

    code, out, err = run(organize("undo", 1, "--yes"), scan)

    assert (code, err) == (0, "")
    assert out == (
        f"Moved back 3 files, 15 B, in {folder} (batch 2, undoing batch 1):\n"
        "  Images/a.jpg -> a.jpg\n"
        "  Audio/c.mp3 -> c.mp3\n"
        "  Documents/b.pdf -> b.pdf\n"
    )
    assert tree(folder) == {**content(SOURCES), **CATEGORIES}
    assert query(data_dir, "SELECT kind, state FROM move_batches ORDER BY id") == [
        ("organize", "done"),
        ("undo", "done"),
    ]


def test_undo_says_what_stays_and_what_was_refused(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.30] [0012.35] [0012.36] a missing file stays, an open one is refused, b goes back
    folder = three_files(zone)
    sorted_by_cli(scan, folder)
    (folder / MOVED[A]).rename(zone / "kept.jpg")
    held = scan_context(tmp_path, zone, data_dir, FakeOpenFiles([folder / MOVED[C]]))

    code, out, _ = run(organize("undo", 1, "--yes"), held)

    assert (code, out) == (
        1,
        f"Moved back 1 file, 5 B, in {folder} (batch 2, undoing batch 1):\n"
        "  Documents/b.pdf -> b.pdf\n"
        "Refused 1:\n"
        f"  open_file: {folder / MOVED[C]}\n"
        "Stays 1:\n"
        "  missing: Images/a.jpg\n",
    )
    assert tree(folder) == {**content({B: B, C: MOVED[C]}), **CATEGORIES}


@pytest.mark.parametrize("yes", [[], ["--yes"]], ids=["plan", "yes"])
def test_nothing_to_move_back(scan: ScanContext, zone: Path, yes: list[str]) -> None:
    # [0012.29] [0012.36] every move undone already
    folder = three_files(zone)
    sorted_by_cli(scan, folder)
    assert run(organize("undo", 1, "--yes"), scan)[0] == 0

    assert run(organize("undo", 1, *yes), scan) == (1, "Nothing to move back from batch 1.\n", "")


def test_every_file_refused_means_no_undo_batch(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.30] [0012.36]
    folder = three_files(zone)
    sorted_by_cli(scan, folder)
    held = scan_context(tmp_path, zone, data_dir, FakeOpenFiles(folder / MOVED[n] for n in SORTED))

    code, out, _ = run(organize("undo", 1, "--yes"), held)

    assert (code, out) == (
        1,
        "Nothing was moved back from batch 1.\n"
        "Refused 3:\n"
        f"  open_file: {folder / MOVED[A]}\n"
        f"  open_file: {folder / MOVED[C]}\n"
        f"  open_file: {folder / MOVED[B]}\n",
    )
    assert query(data_dir, "SELECT COUNT(*) FROM move_batches") == [(1,)]


@pytest.mark.parametrize("yes", [[], ["--yes"]], ids=["plan", "yes"])
def test_a_batch_that_cannot_be_undone_is_refused(
    scan: ScanContext, zone: Path, yes: list[str]
) -> None:
    # [0012.29] [0012.36] one that does not exist, and an undo batch: organize again instead
    folder = three_files(zone)
    sorted_by_cli(scan, folder)
    assert run(organize("undo", 1, "--yes"), scan)[0] == 0

    assert run(organize("undo", 7, *yes), scan) == (1, "Refused: batch 7: not_found\n", "")
    assert run(organize("undo", 2, *yes), scan) == (1, "Refused: batch 2: undo_batch\n", "")
    assert tree(folder) == {**content(SOURCES), **CATEGORIES}


def test_an_undo_that_stopped_names_the_batch_it_undoes(
    scan: ScanContext, zone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0012.35] [0012.36] a cannot go back, so nothing did: undoing batch 1 again takes them all
    folder = three_files(zone)
    sorted_by_cli(scan, folder)
    rename = FlakyRename({folder / MOVED[A]: "before"})
    monkeypatch.setattr(cli_organize, "carry_out", functools.partial(carry_out, rename=rename))

    code, out, _ = run(organize("undo", 1, "--yes"), scan)

    assert (code, out) == (
        3,
        f"Stopped: [Errno 13] refused before the move: '{folder / MOVED[A]}'\n"
        "  [2] rolled_back: the undo of batch 1 stopped;"
        " 'kresorter organize undo 1' moves back the files still sorted\n",
    )
    assert tree(folder) == {**content(SORTED), **CATEGORIES}


# --- organize list -----------------------------------------------------------------------------


def test_list_shows_the_batches_newest_first(
    tmp_path: Path, scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.34] id, date, kind, files moved, state, undone or not, folder; it changes nothing
    folder = three_files(zone)
    sorted_by_cli(scan, folder)
    (folder / MOVED[A]).rename(zone / "kept.jpg")
    assert run(organize("undo", 1, "--yes"), scan)[0] == 0
    other = zone / "Desktop"
    write(other / "e.zip", b"e.zip")
    sorted_by_cli(scan, other)
    held = scan_context(tmp_path, zone, data_dir, FakeOpenFiles([other / "Archives" / "e.zip"]))
    assert run(organize("undo", 3, "--yes"), held)[0] == 1
    before = tree(tmp_path)

    code, out, err = run(organize("list"), scan)

    assert (code, err) == (0, "")
    assert out == (
        "Organize batches: 3\n"
        f"  [3] {created(data_dir, 3)}  organize  1 file moved  done  {other}\n"
        f"  [2] {created(data_dir, 2)}  undo of batch 1  2 files moved  done  {folder}\n"
        f"  [1] {created(data_dir, 1)}  organize  3 files moved  done, partly undone  {folder}\n"
    )
    assert tree(tmp_path) == before


def test_list_says_when_a_batch_is_undone(scan: ScanContext, zone: Path, data_dir: Path) -> None:
    # [0012.34]
    folder = three_files(zone)
    sorted_by_cli(scan, folder)
    assert run(organize("undo", 1, "--yes"), scan)[0] == 0

    _, out, _ = run(organize("list"), scan)

    assert out.endswith(
        f"  [1] {created(data_dir, 1)}  organize  3 files moved  done, undone  {folder}\n"
    )


def test_list_without_batches(scan: ScanContext) -> None:
    # [0012.34]
    assert run(organize("list"), scan) == (0, "No organize batches.\n", "")


def test_list_recovers_organize_first(scan: ScanContext, zone: Path, data_dir: Path) -> None:
    # [0012.1] [0012.34] like every organize command
    data_dir.mkdir(parents=True)
    folder = three_files(zone)
    crash(data_dir / "journal.db", folder, planned(folder), {folder / C: "exit-before"})

    code, out, _ = run(organize("list"), scan)

    assert code == 0
    assert out.endswith(
        "Organize batches: 1\n"
        f"  [1] {created(data_dir, 1)}  organize  2 files moved  failed  {folder}\n"
    )
    assert out.startswith("Recovered 1 interrupted organize batch:\n")


def test_list_runs_while_another_domain_is_unfinished(
    scan: ScanContext, zone: Path, data_dir: Path
) -> None:
    # [0012.34] as quarantine list does
    quarantine_left_pending(scan, zone, data_dir)

    assert run(organize("list"), scan) == (0, "No organize batches.\n", "")
    assert query(data_dir, "SELECT state FROM operations") == [("pending",)]
