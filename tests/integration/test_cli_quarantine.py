"""`safeclean quarantine add / list / restore / purge`: end-to-end on a real temporary tree.

Every quarantine command opens the journal in the app data directory and runs ``recover()``
first. Purge deletes only with ``--yes``; without it the plan is shown and nothing changes
(decision 0008: plan and confirmation in the same process).
"""

import functools
import os
import time
from pathlib import Path, PurePath

import pytest

from fakes import FakeOpenFiles, journal_held
from safeclean import cli, cli_quarantine
from safeclean.core.heuristics import Platform
from safeclean.core.open_files import NoOpenFileCheck, ProcFdChecker
from safeclean.core.scanner import ScanContext
from safeclean.quarantine.service import QuarantineService
from safeclean.storage.lock import InstanceLock
from support.cli import run, scan_context
from support.files import write
from support.journal import query

# --- helpers -----------------------------------------------------------------------------------


@pytest.fixture
def context(tmp_path: Path, zone: Path, data_dir: Path) -> ScanContext:
    return scan_context(tmp_path, zone, data_dir)


def states(data_dir: Path) -> list[tuple[object, ...]]:
    return query(data_dir, "SELECT id, state FROM items ORDER BY id")


def slot(data_dir: Path, item_id: int) -> Path:
    ((vault_path,),) = query(data_dir, "SELECT vault_path FROM items WHERE id = ?", item_id)
    return Path(str(vault_path))


# --- the whole cycle ---------------------------------------------------------------------------


def test_add_list_restore_purge_cycle(context: ScanContext, zone: Path, data_dir: Path) -> None:
    write(zone / "a.bin", b"aaa")
    write(zone / "b.bin", b"bbbbb")

    code, out, err = run(["quarantine", "add", str(zone / "a.bin"), str(zone / "b.bin")], context)
    assert (code, err) == (0, "")
    assert "Quarantined 2 files, 8 B" in out
    assert not (zone / "a.bin").exists()
    assert not (zone / "b.bin").exists()

    code, out, _ = run(["quarantine", "list"], context)
    assert code == 0
    assert "Quarantine: 2 files, 8 B" in out
    assert f"[1] {zone / 'a.bin'}  3 B" in out
    assert f"[2] {zone / 'b.bin'}  5 B" in out

    code, out, _ = run(["quarantine", "restore", "1"], context)
    assert code == 0
    assert f"Restored 1 file:\n  [1] {zone / 'a.bin'}" in out
    assert (zone / "a.bin").read_bytes() == b"aaa"

    code, out, _ = run(["quarantine", "purge", "--yes", "2"], context)
    assert code == 0
    assert "Permanently deleted 1 file, 5 B" in out
    assert not slot(data_dir, 2).exists()
    assert not (zone / "b.bin").exists()
    assert states(data_dir) == [(1, "restored"), (2, "purged")]

    _, out, _ = run(["quarantine", "list"], context)
    assert "Quarantine: 0 files, 0 B" in out


# --- purge needs --yes -------------------------------------------------------------------------


def test_purge_without_yes_shows_the_plan_and_deletes_nothing(
    context: ScanContext, zone: Path, data_dir: Path
) -> None:
    write(zone / "a.bin", b"aaa")
    run(["quarantine", "add", str(zone / "a.bin")], context)

    code, out, _ = run(["quarantine", "purge", "1"], context)

    assert code == 1
    assert "Would permanently delete 1 file, 3 B" in out
    assert f"[1] {zone / 'a.bin'}  3 B" in out
    assert "Nothing was deleted. Re-run with --yes" in out
    assert slot(data_dir, 1).read_bytes() == b"aaa"
    assert states(data_dir) == [(1, "quarantined")]
    assert query(data_dir, "SELECT COUNT(*) FROM operations WHERE kind = 'purge'") == [(0,)]


def test_purge_shows_refusals_and_exits_1(context: ScanContext, zone: Path) -> None:
    write(zone / "a.bin")
    run(["quarantine", "add", str(zone / "a.bin")], context)

    code, out, _ = run(["quarantine", "purge", "--yes", "1", "999"], context)

    assert code == 1
    assert "Permanently deleted 1 file" in out
    assert "[999] unknown_item" in out


def test_purge_with_nothing_to_delete_exits_1(context: ScanContext) -> None:
    code, out, _ = run(["quarantine", "purge", "--yes", "999"], context)
    assert code == 1
    assert "Nothing to delete" in out


# --- add ---------------------------------------------------------------------------------------


def test_add_reports_refusals_and_exits_1(tmp_path: Path, context: ScanContext, zone: Path) -> None:
    write(zone / "a.bin")
    write(tmp_path / "system" / "kernel.bin")
    (zone / "dir").mkdir()

    code, out, _ = run(
        [
            "quarantine",
            "add",
            str(zone / "a.bin"),
            str(tmp_path / "system" / "kernel.bin"),
            str(zone / "dir"),
            str(zone / "missing.bin"),
        ],
        context,
    )

    assert code == 1
    assert "Quarantined 1 file" in out
    assert f"blocked (system): {tmp_path / 'system' / 'kernel.bin'}" in out
    assert f"not_regular: {zone / 'dir'}" in out
    assert f"not_found: {zone / 'missing.bin'}" in out
    assert (tmp_path / "system" / "kernel.bin").exists()
    assert (zone / "dir").is_dir()


def test_add_refuses_an_open_file(tmp_path: Path, zone: Path, data_dir: Path) -> None:
    write(zone / "a.bin")
    context = scan_context(tmp_path, zone, data_dir, FakeOpenFiles([zone / "a.bin"]))

    code, out, _ = run(["quarantine", "add", str(zone / "a.bin")], context)

    assert code == 1
    assert f"open_file: {zone / 'a.bin'}" in out
    assert (zone / "a.bin").exists()


def test_add_takes_relative_paths(
    context: ScanContext, zone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(zone / "a.bin")
    monkeypatch.chdir(zone)

    code, out, _ = run(["quarantine", "add", "a.bin"], context)

    assert code == 0
    assert f"[1] {zone / 'a.bin'}" in out


def test_without_a_reliable_open_file_check_nothing_moves(
    tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    write(zone / "a.bin")
    context = scan_context(tmp_path, zone, data_dir, NoOpenFileCheck())

    code, out, err = run(["quarantine", "add", str(zone / "a.bin")], context)

    assert code == 3
    assert out == ""
    assert "open-file check" in err
    assert (zone / "a.bin").exists()


def test_a_failed_move_is_rolled_back_and_reported(
    context: ScanContext, zone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_move(source: Path, target: Path) -> None:
        raise OSError(5, "I/O error")

    monkeypatch.setattr(
        cli_quarantine, "QuarantineService", functools.partial(QuarantineService, move=broken_move)
    )
    write(zone / "a.bin")

    code, out, _ = run(["quarantine", "add", str(zone / "a.bin")], context)

    assert code == 1
    assert "Stopped: [Errno 5] I/O error" in out
    assert (zone / "a.bin").exists()


def test_unusable_data_directory_exits_3(tmp_path: Path, zone: Path) -> None:
    write(tmp_path / "data")  # a file where the data directory's parent should be
    context = scan_context(tmp_path, zone, tmp_path / "data" / "safeclean")

    code, out, err = run(["quarantine", "list"], context)

    assert code == 3
    assert out == ""
    assert "cannot use the data directory" in err


def test_unopenable_journal_exits_3(context: ScanContext, data_dir: Path) -> None:
    (data_dir / "journal.db").mkdir(parents=True)  # a directory where the journal should be

    code, out, err = run(["quarantine", "list"], context)

    assert code == 3
    assert out == ""
    assert "cannot open the journal" in err


def test_a_vault_that_cannot_be_created_is_named(context: ScanContext, data_dir: Path) -> None:
    vault = write(data_dir / "quarantine")  # a file where the vault should be

    code, out, err = run(["quarantine", "list"], context)

    assert (code, out) == (3, "")
    assert err == f"safeclean: cannot use the vault: [Errno 17] File exists: '{vault}'\n"


def test_a_journal_failure_stops_and_names_safeclean_recover(
    context: ScanContext, data_dir: Path, zone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(zone / "a.bin")
    data_dir.mkdir(parents=True)

    with journal_held(monkeypatch, data_dir):
        code, out, err = run(["quarantine", "add", str(path)], context)

    assert (code, out) == (3, "")
    assert err == "safeclean: journal failed: database is locked; run 'safeclean recover'\n"
    assert path.read_bytes() == b"payload"
    assert query(data_dir, "SELECT COUNT(*) FROM operations") == [(0,)]


def test_data_directory_inside_a_scan_zone_exits_3(tmp_path: Path, zone: Path) -> None:
    context = scan_context(tmp_path, zone, zone / "safeclean")

    code, _, err = run(["quarantine", "list"], context)

    assert code == 3
    assert "inside scan zone" in err
    assert not (zone / "safeclean").exists()  # refused before anything is created there


def test_a_second_safeclean_on_the_same_data_directory_exits_3(
    context: ScanContext, zone: Path, data_dir: Path
) -> None:
    write(zone / "a.bin")
    data_dir.mkdir(parents=True)

    with InstanceLock(data_dir / "safeclean.lock"):
        code, out, err = run(["quarantine", "add", str(zone / "a.bin")], context)

    assert code == 3
    assert out == ""
    assert "another safeclean" in err
    assert (zone / "a.bin").exists()
    assert not (data_dir / "journal.db").exists()  # locked out before the journal is opened


def test_the_lock_is_released_after_each_command(context: ScanContext, data_dir: Path) -> None:
    run(["quarantine", "list"], context)

    with InstanceLock(data_dir / "safeclean.lock"):
        pass


def test_data_directory_is_created_private(context: ScanContext, data_dir: Path) -> None:
    run(["quarantine", "list"], context)

    assert (data_dir / "journal.db").is_file()
    assert data_dir.stat().st_mode & 0o777 == 0o700


# --- restore -----------------------------------------------------------------------------------


def test_restore_conflict_is_reported_and_exits_1(context: ScanContext, zone: Path) -> None:
    write(zone / "a.bin", b"old")
    run(["quarantine", "add", str(zone / "a.bin")], context)
    write(zone / "a.bin", b"newcomer")

    code, out, _ = run(["quarantine", "restore", "1"], context)

    assert code == 1
    assert "[1] conflict" in out
    assert (zone / "a.bin").read_bytes() == b"newcomer"


# --- recovery at startup -----------------------------------------------------------------------


def test_every_quarantine_command_recovers_first(
    context: ScanContext, zone: Path, data_dir: Path
) -> None:
    write(zone / "a.bin")
    run(["quarantine", "add", str(zone / "a.bin")], context)
    # As a crash right after the rename would leave it: journaled, moved, not yet confirmed.
    query(data_dir, "UPDATE items SET state = 'pending'")
    query(data_dir, "UPDATE operations SET state = 'pending'")

    code, out, _ = run(["quarantine", "list"], context)

    assert code == 0
    assert "Recovered an interrupted quarantine operation (1 file)" in out
    assert f"[1] {zone / 'a.bin'}" in out
    assert states(data_dir) == [(1, "quarantined")]


def test_lost_items_are_warned_about_on_stderr(
    context: ScanContext, zone: Path, data_dir: Path
) -> None:
    write(zone / "a.bin")
    run(["quarantine", "add", str(zone / "a.bin")], context)
    query(data_dir, "UPDATE items SET state = 'pending'")
    slot(data_dir, 1).write_bytes(b"tampered")

    code, _, err = run(["quarantine", "list"], context)

    assert code == 0
    assert "LOST" in err
    assert str(zone / "a.bin") in err


# --- usage -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["quarantine"],
        ["quarantine", "add"],
        ["quarantine", "restore"],
        ["quarantine", "restore", "abc"],
        ["quarantine", "purge"],
        ["quarantine", "purge", "--yes"],
    ],
)
def test_bad_usage_exits_with_2(context: ScanContext, args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        run(args, context)
    assert exc.value.code == 2


# --- scan now uses the real open-file check ----------------------------------------------------


def test_scan_context_on_linux_checks_open_files(tmp_path: Path) -> None:
    context = cli.default_context(platform="linux", env={}, home=tmp_path)
    assert isinstance(context.open_files, ProcFdChecker)
    assert context.open_files_checked is True


@pytest.mark.parametrize("platform", ["darwin", "windows"])
def test_scan_context_elsewhere_discloses_the_missing_check(
    tmp_path: Path, platform: Platform
) -> None:
    env = {"USERPROFILE": r"C:\Users\Alice"}
    context = cli.default_context(platform=platform, env=env, home=tmp_path)
    assert context.open_files_checked is False
    assert context.open_files.reliable is False


def test_a_loosened_data_directory_is_made_private_again(
    context: ScanContext, data_dir: Path
) -> None:
    run(["quarantine", "list"], context)
    data_dir.chmod(0o755)

    run(["quarantine", "list"], context)

    assert data_dir.stat().st_mode & 0o777 == 0o700


# --- bulk add from an analysis (decision 0010, item 14) ----------------------------------------

DAY_NS = 86_400 * 10**9


def aged(path: Path, days: int) -> Path:
    stamp = time.time_ns() - days * DAY_NS
    os.utime(path, ns=(stamp, stamp))
    return path


@pytest.fixture
def junk(zone: Path) -> dict[str, Path]:
    """One SAFE file (bytecode), one LIKELY_SAFE copy and its kept original, one plain file."""
    return {
        "pyc": write(zone / "proj" / "__pycache__" / "m.cpython-313.pyc", b"bytecode"),
        "original": aged(write(zone / "photos" / "img.jpg", b"jpeg-bytes"), 10),
        "copy": aged(write(zone / "backup" / "img.jpg", b"jpeg-bytes"), 5),
        "notes": write(zone / "notes.txt", b"hello"),
    }


def test_bulk_add_without_yes_shows_the_plan_and_moves_nothing(
    context: ScanContext, junk: dict[str, Path], data_dir: Path
) -> None:
    code, out, _ = run(["quarantine", "add", "--from-analysis", "--level", "safe"], context)

    assert code == 1
    assert out.splitlines() == [
        "Would quarantine 1 file, 8 B (level: safe):",
        f"  {junk['pyc']}  8 B",
        "    junk_cache: python-bytecode",
        "Nothing was moved. Re-run with --yes to quarantine these files.",
    ]
    assert all(path.exists() for path in junk.values())
    assert states(data_dir) == []


def test_bulk_add_with_yes_moves_only_the_chosen_level(
    context: ScanContext, junk: dict[str, Path], data_dir: Path
) -> None:
    args = ["quarantine", "add", "--from-analysis", "--level", "safe", "--yes"]
    code, out, err = run(args, context)

    assert (code, err) == (0, "")
    assert out.splitlines() == ["Quarantined 1 file, 8 B", f"  [1] {junk['pyc']}"]
    assert not junk["pyc"].exists()
    assert junk["copy"].exists()
    assert states(data_dir) == [(1, "quarantined")]


def test_likely_safe_includes_safe_and_keeps_the_original(
    context: ScanContext, junk: dict[str, Path]
) -> None:
    args = ["quarantine", "add", "--from-analysis", "--level", "likely_safe", "--yes"]
    code, out, _ = run(args, context)

    assert code == 0
    assert "Quarantined 2 files, 18 B" in out
    assert not junk["pyc"].exists()
    assert not junk["copy"].exists()
    assert junk["original"].read_bytes() == b"jpeg-bytes"
    assert junk["notes"].exists()


def test_bulk_add_never_moves_a_kept_copy_even_when_it_is_junk(
    context: ScanContext, zone: Path
) -> None:
    kept = aged(write(zone / "a" / "__pycache__" / "x.pyc", b"same"), 9)
    copy = aged(write(zone / "b" / "__pycache__" / "x.pyc", b"same"), 3)

    args = ["quarantine", "add", "--from-analysis", "--level", "likely_safe", "--yes"]
    code, _, _ = run(args, context)

    assert code == 0
    assert kept.read_bytes() == b"same"
    assert not copy.exists()


def test_bulk_add_analyzes_only_the_given_paths(
    context: ScanContext, junk: dict[str, Path]
) -> None:
    root = str(junk["pyc"].parent.parent)
    args = ["quarantine", "add", "--from-analysis", root, "--level", "likely_safe", "--yes"]
    code, out, _ = run(args, context)

    assert code == 0
    assert "Quarantined 1 file, 8 B" in out
    assert junk["copy"].exists()


class OpenedAfterTheScan:
    """Reports ``target`` closed while it is scanned and open from then on."""

    reliable = True

    def __init__(self, target: Path) -> None:
        self._target = target
        self._checks = 0

    def is_open(self, path: PurePath) -> bool:
        if path != self._target:
            return False
        self._checks += 1
        return self._checks > 1


def test_bulk_add_rechecks_each_file_and_moves_the_rest(
    tmp_path: Path, zone: Path, data_dir: Path, junk: dict[str, Path]
) -> None:
    context = scan_context(tmp_path, zone, data_dir, OpenedAfterTheScan(junk["pyc"]))

    args = ["quarantine", "add", "--from-analysis", "--level", "likely_safe", "--yes"]
    code, out, _ = run(args, context)

    assert code == 1
    assert f"open_file: {junk['pyc']}" in out
    assert junk["pyc"].exists()
    assert not junk["copy"].exists()


def test_bulk_add_with_nothing_to_quarantine_exits_1(context: ScanContext, zone: Path) -> None:
    write(zone / "notes.txt", b"hello")

    args = ["quarantine", "add", "--from-analysis", "--level", "likely_safe", "--yes"]
    code, out, _ = run(args, context)

    assert code == 1
    assert out == "Nothing to quarantine.\n"


@pytest.mark.parametrize("confirm", [[], ["--yes"]])
def test_bulk_add_without_a_reliable_open_file_check_exits_3(
    tmp_path: Path, zone: Path, data_dir: Path, junk: dict[str, Path], confirm: list[str]
) -> None:
    context = scan_context(tmp_path, zone, data_dir, NoOpenFileCheck())

    args = ["quarantine", "add", "--from-analysis", "--level", "safe", *confirm]
    code, out, err = run(args, context)

    assert code == 3
    assert out == ""
    assert "open-file check" in err
    assert all(path.exists() for path in junk.values())


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["quarantine", "add"], "or use --from-analysis"),
        (["quarantine", "add", "--level", "safe", "a.bin"], "only go with --from-analysis"),
        (["quarantine", "add", "--yes", "a.bin"], "only go with --from-analysis"),
        (["quarantine", "add", "--from-analysis"], "needs --level"),
        (["quarantine", "add", "--from-analysis", "--level", "review"], "invalid choice: 'review'"),
    ],
)
def test_bulk_add_bad_usage_exits_with_2(
    context: ScanContext, capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(args, context)

    assert exc.value.code == 2
    assert message in capsys.readouterr().err
