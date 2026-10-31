"""`safeclean quarantine add / list / restore / purge`: end-to-end on a real temporary tree.

Every quarantine command opens the journal in the app data directory and runs ``recover()``
first. Purge deletes only with ``--yes``; without it the plan is shown and nothing changes
(decision 0008: plan and confirmation in the same process).
"""

import functools
import io
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy
from safeclean import cli, cli_quarantine
from safeclean.core.heuristics import JunkClassifier, Platform, default_rules
from safeclean.core.open_files import NoOpenFileCheck, OpenFileChecker, ProcFdChecker
from safeclean.core.scanner import ScanContext
from safeclean.quarantine.service import QuarantineService
from safeclean.storage.db import connect

# --- helpers -----------------------------------------------------------------------------------


def write(path: Path, data: bytes = b"payload") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def zone(tmp_path: Path) -> Path:
    path = tmp_path / "zone"
    path.mkdir()
    return path


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data" / "safeclean"


def ctx(
    tmp_path: Path, zone: Path, data_dir: Path, open_files: OpenFileChecker | None = None
) -> ScanContext:
    # tmp_path lives under /tmp, which the "posix-temp" rule marks as junk: drop it, as in
    # test_cli_scan, or the data directory itself would look like junk and be refused.
    rules = [r for r in default_rules() if r.id != "posix-temp"]
    checker = open_files or FakeOpenFiles()
    policy = make_policy(tmp_path, tmp_path / "system", default_roots=[zone], app_data_dir=data_dir)
    return ScanContext(
        policy=policy,
        open_files=checker,
        classifier=JunkClassifier(rules, platform="linux"),
        open_files_checked=checker.reliable,
    )


@pytest.fixture
def context(tmp_path: Path, zone: Path, data_dir: Path) -> ScanContext:
    return ctx(tmp_path, zone, data_dir)


def run(args: list[str], context: ScanContext) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(args, out=out, err=err, context_factory=lambda: context)
    return code, out.getvalue(), err.getvalue()


def query(data_dir: Path, sql: str, *params: object) -> list[tuple[object, ...]]:
    """Read the CLI's journal after the commands under test have run."""
    conn = connect(data_dir / "journal.db")
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


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
    context = ctx(tmp_path, zone, data_dir, FakeOpenFiles([zone / "a.bin"]))

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
    context = ctx(tmp_path, zone, data_dir, NoOpenFileCheck())

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
    context = ctx(tmp_path, zone, tmp_path / "data" / "safeclean")

    code, out, err = run(["quarantine", "list"], context)

    assert code == 3
    assert out == ""
    assert "cannot open the journal" in err


def test_data_directory_inside_a_scan_zone_exits_3(tmp_path: Path, zone: Path) -> None:
    context = ctx(tmp_path, zone, zone / "safeclean")

    code, _, err = run(["quarantine", "list"], context)

    assert code == 3
    assert "inside scan zone" in err
    assert not (zone / "safeclean").exists()  # refused before anything is created there


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
    assert "Recovered an interrupted operation (1 file)" in out
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
