"""`safeclean autostart disable|enable ID [--yes]`: end-to-end (step 4, commit 12c2b).

The id is the beginning of an entry's digest, as `autostart list` shows it (12 characters); any
beginning that names one entry is accepted. A changed entry has another digest, so its old id
names nothing. Without ``--yes`` the command shows what would be written and changes nothing
(exit 1). With it, the change runs in the shared journal session, after the autostart
``recover()``. Exit codes: 0 done; 1 refused, rolled back, not confirmed or no such entry;
2 usage; 3 failed, unfinished quarantine work, or the journal cannot be used safely.
"""

import io
import json
import plistlib
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, FakeRegistry, deny_stat, journal_held, make_policy
from safeclean import cli
from safeclean.autostart.changes import ChangeResult, ChangeState
from safeclean.autostart.listing import AutostartContext
from safeclean.autostart.models import AutostartItem
from safeclean.autostart.registry import Hive, RegistryError, RegValue, UserRegistry, ValueKind
from safeclean.autostart.run_changes import RunKeyChanges
from safeclean.autostart.run_keys import APPROVED, RUN, RUN_ONCE
from safeclean.autostart.xdg_changes import STUB, hidden_copy
from safeclean.core.heuristics import JunkClassifier, Platform, default_rules
from safeclean.core.scanner import ScanContext
from safeclean.storage.db import connect

APP = b"[Desktop Entry]\nType=Application\nName=App\nExec=/usr/bin/app --tray\n"
SYNC = RegValue("Sync", ValueKind.REG_SZ, r"C:\sync.exe")


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data" / "safeclean"


@pytest.fixture
def scan(tmp_path: Path, data_dir: Path) -> ScanContext:
    # As in test_cli_quarantine: tmp_path is under /tmp, which "posix-temp" marks as junk.
    zone = tmp_path / "zone"
    zone.mkdir()
    rules = [r for r in default_rules() if r.id != "posix-temp"]
    policy = make_policy(tmp_path, tmp_path / "system", default_roots=[zone], app_data_dir=data_dir)
    return ScanContext(policy, FakeOpenFiles(), JunkClassifier(rules, platform="linux"), True)


@pytest.fixture
def user(tmp_path: Path) -> Path:
    return tmp_path / "config" / "autostart"


@pytest.fixture
def system(tmp_path: Path) -> Path:
    return tmp_path / "etc" / "xdg" / "autostart"


def autostart(
    platform: Platform, tmp_path: Path, registry: UserRegistry | None = None
) -> AutostartContext:
    env = {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CONFIG_DIRS": str(tmp_path / "etc" / "xdg"),
    }
    return AutostartContext(
        platform, env, home=tmp_path, root=tmp_path, registry=lambda: registry or FakeRegistry({})
    )


def run(args: list[str], scan: ScanContext, auto: AutostartContext) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        args, out=out, err=err, context_factory=lambda: scan, autostart_context=lambda: auto
    )
    return code, out.getvalue(), err.getvalue()


def listed(scan: ScanContext, auto: AutostartContext) -> list[dict[str, object]]:
    _, out, _ = run(["autostart", "list", "--json"], scan, auto)
    items: list[dict[str, object]] = json.loads(out)["items"]
    return items


def only_id(scan: ScanContext, auto: AutostartContext) -> str:
    (item,) = listed(scan, auto)
    return str(item["digest"])[:12]


def rows(data_dir: Path) -> list[tuple[object, ...]]:
    if not (data_dir / "journal.db").exists():
        return []
    conn = connect(data_dir / "journal.db")
    try:
        return conn.execute("SELECT id, action, state FROM autostart_changes").fetchall()
    finally:
        conn.close()


# --- the id --------------------------------------------------------------------------------------


def test_list_shows_the_id_of_each_entry(tmp_path: Path, scan: ScanContext, user: Path) -> None:
    entry = write(user / "app.desktop", APP)
    auto = autostart("linux", tmp_path)

    _, out, _ = run(["autostart", "list"], scan, auto)

    assert f"    location: {entry}\n    id: {only_id(scan, auto)}\n" in out  # the last line


def test_any_unique_beginning_of_the_digest_names_the_entry(
    tmp_path: Path, scan: ScanContext, user: Path
) -> None:
    write(user / "app.desktop", APP)
    auto = autostart("linux", tmp_path)

    code, out, _ = run(
        ["autostart", "disable", only_id(scan, auto)[:3].upper(), "--yes"], scan, auto
    )

    assert (code, out) == (0, "Disabled app (change 1).\n")


def test_an_id_naming_nothing_says_the_entry_may_have_changed(
    tmp_path: Path, scan: ScanContext, user: Path, data_dir: Path
) -> None:
    entry = write(user / "app.desktop", APP)
    auto = autostart("linux", tmp_path)
    old = only_id(scan, auto)
    entry.write_bytes(APP + b"Comment=edited\n")

    code, out, _ = run(["autostart", "disable", old, "--yes"], scan, auto)

    assert code == 1
    assert out == (
        f"No autostart entry has id {old}; it may have changed since it was listed."
        " Run 'safeclean autostart list'.\n"
    )
    assert rows(data_dir) == []


def test_an_id_naming_several_entries_is_refused(
    tmp_path: Path, scan: ScanContext, user: Path, data_dir: Path
) -> None:
    for n in range(17):  # 17 digests: two of them begin with the same hex digit
        write(user / f"app{n}.desktop", APP.replace(b"Name=App", b"Name=App%d" % n))
    auto = autostart("linux", tmp_path)
    firsts = [str(item["digest"])[0] for item in listed(scan, auto)]
    shared = next(c for c in firsts if firsts.count(c) > 1)

    code, out, _ = run(["autostart", "disable", shared, "--yes"], scan, auto)

    assert (code, out) == (
        1,
        f"Id {shared} matches {firsts.count(shared)} entries; give more of it.\n",
    )
    assert rows(data_dir) == []


@pytest.mark.parametrize("bad", ["xyz", "", "0" * 33])
def test_an_id_that_is_not_hex_is_a_usage_error(
    tmp_path: Path, scan: ScanContext, bad: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(["autostart", "disable", bad], scan, autostart("linux", tmp_path))

    assert exc.value.code == 2
    assert "argument id: not the beginning of an autostart id" in capsys.readouterr().err


# --- confirmation --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scope", "how"),
    [
        (
            "user",
            "  its file is replaced by a copy with Hidden=true; the original is kept in the"
            " autostart store\n",
        ),
        (
            "system",
            "  a stub with Hidden=true is created in {user}; the system file is never written\n",
        ),
    ],
)
def test_without_yes_it_shows_what_would_be_written_and_changes_nothing(
    tmp_path: Path,
    scan: ScanContext,
    user: Path,
    system: Path,
    data_dir: Path,
    scope: str,
    how: str,
) -> None:
    entry = write((user if scope == "user" else system) / "app.desktop", APP)
    auto = autostart("linux", tmp_path)

    code, out, _ = run(["autostart", "disable", only_id(scan, auto)], scan, auto)

    assert code == 1
    assert out == (
        f"Would disable app (xdg_autostart, {scope}):\n"
        f"  location: {entry}\n"
        + how.format(user=user)
        + "Nothing was changed. Re-run with --yes to disable it.\n"
    )
    assert entry.read_bytes() == APP
    assert [p.name for p in tmp_path.rglob("*.desktop")] == ["app.desktop"]  # no stub
    assert rows(data_dir) == []
    assert not (data_dir / "autostart").exists()  # no store either (item 115)


def test_enable_without_yes_says_nothing_is_deleted(
    tmp_path: Path, scan: ScanContext, user: Path
) -> None:
    entry = write(user / "app.desktop", hidden_copy(APP))
    auto = autostart("linux", tmp_path)

    code, out, _ = run(["autostart", "enable", only_id(scan, auto)], scan, auto)

    assert code == 1
    assert out == (
        "Would enable app (xdg_autostart, user):\n"
        f"  location: {entry}\n"
        "  if safeclean disabled it, what it changed is put back (the original from the store,"
        " or the stub moved to the store); nothing is deleted\n"
        "Nothing was changed. Re-run with --yes to enable it.\n"
    )


# --- with --yes ----------------------------------------------------------------------------------


def test_disable_then_enable_an_own_entry(
    tmp_path: Path, scan: ScanContext, user: Path, data_dir: Path
) -> None:
    entry = write(user / "app.desktop", APP)
    auto = autostart("linux", tmp_path)

    disabled = run(["autostart", "disable", only_id(scan, auto), "--yes"], scan, auto)
    hidden = entry.read_bytes()
    enabled = run(["autostart", "enable", only_id(scan, auto), "--yes"], scan, auto)

    assert disabled == (0, "Disabled app (change 1).\n", "")
    assert hidden == hidden_copy(APP)
    assert enabled == (0, "Enabled app (change 2).\n", "")
    assert entry.read_bytes() == APP
    assert rows(data_dir) == [(1, "disable", "done"), (2, "enable", "done")]


def test_disable_a_system_entry_creates_the_user_stub(
    tmp_path: Path, scan: ScanContext, user: Path, system: Path
) -> None:
    write(system / "app.desktop", APP)
    auto = autostart("linux", tmp_path)

    code, _, _ = run(["autostart", "disable", only_id(scan, auto), "--yes"], scan, auto)

    assert code == 0
    assert (user / "app.desktop").read_bytes() == STUB
    assert (system / "app.desktop").read_bytes() == APP


def test_an_entry_already_in_that_state_has_nothing_to_do(
    tmp_path: Path, scan: ScanContext, user: Path, data_dir: Path
) -> None:
    write(user / "app.desktop", hidden_copy(APP))
    auto = autostart("linux", tmp_path)

    code, out, _ = run(["autostart", "disable", only_id(scan, auto), "--yes"], scan, auto)

    assert (code, out) == (1, "app is already disabled; nothing to do.\n")
    assert rows(data_dir) == []


def test_a_refusal_of_the_change_is_shown(tmp_path: Path, scan: ScanContext, user: Path) -> None:
    write(user / "app.desktop", hidden_copy(APP))  # disabled, but not by safeclean
    auto = autostart("linux", tmp_path)

    code, out, _ = run(["autostart", "enable", only_id(scan, auto), "--yes"], scan, auto)

    assert code == 1
    assert (
        out == "Refused: foreign: not disabled by safeclean; enabling it would edit its content\n"
    )


def test_an_interrupted_change_is_recovered_first(
    tmp_path: Path, scan: ScanContext, user: Path, data_dir: Path
) -> None:
    write(user / "app.desktop", APP)
    auto = autostart("linux", tmp_path)
    run(["autostart", "disable", only_id(scan, auto), "--yes"], scan, auto)
    conn = connect(data_dir / "journal.db")
    conn.execute("UPDATE autostart_changes SET state = 'pending', finished_at_ns = NULL")
    conn.close()

    code, out, _ = run(["autostart", "enable", only_id(scan, auto), "--yes"], scan, auto)

    assert code == 0
    assert out == (
        "Recovered 1 interrupted autostart change:\n  [1] done\nEnabled app (change 2).\n"
    )


def test_unfinished_quarantine_work_names_its_command(
    tmp_path: Path, scan: ScanContext, user: Path, data_dir: Path
) -> None:
    entry = write(user / "app.desktop", APP)
    auto = autostart("linux", tmp_path)
    data_dir.mkdir(parents=True)
    conn = connect(data_dir / "journal.db")
    conn.execute(
        "INSERT INTO operations (kind, state, created_at_ns) VALUES ('quarantine', 'pending', 1)"
    )
    conn.close()

    code, out, err = run(["autostart", "disable", only_id(scan, auto), "--yes"], scan, auto)

    assert (code, out) == (3, "")
    assert err == (
        "safeclean: a quarantine operation is unfinished; run 'safeclean quarantine list'"
        " first; nothing was changed\n"
    )
    assert entry.read_bytes() == APP


def test_a_check_before_acting_that_fails_stops_with_the_reason(
    tmp_path: Path,
    scan: ScanContext,
    data_dir: Path,
    user: Path,
    system: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write(system / "app.desktop", APP)
    user.mkdir(parents=True)
    auto = autostart("linux", tmp_path)
    change_id = only_id(scan, auto)
    deny_stat(monkeypatch, user)  # where the stub would go: its device cannot be known

    code, out, err = run(["autostart", "disable", change_id, "--yes"], scan, auto)

    monkeypatch.undo()
    assert (code, out) == (3, "")
    assert err == (
        f"safeclean: cannot disable app: [Errno 13] Permission denied: '{user}';"
        " nothing was changed\n"
    )
    assert rows(data_dir) == []
    assert list(user.iterdir()) == []


def test_a_journal_failure_stops_and_names_autostart_recover(
    tmp_path: Path,
    scan: ScanContext,
    data_dir: Path,
    user: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = write(user / "app.desktop", APP)
    auto = autostart("linux", tmp_path)
    change_id = only_id(scan, auto)
    data_dir.mkdir(parents=True)

    with journal_held(monkeypatch, data_dir):
        code, out, err = run(["autostart", "disable", change_id, "--yes"], scan, auto)

    assert (code, out) == (3, "")
    assert err == (
        "safeclean: journal failed: database is locked; run 'safeclean autostart recover'\n"
    )
    assert rows(data_dir) == []
    assert entry.read_bytes() == APP


# --- Windows -------------------------------------------------------------------------------------


def test_disable_an_hkcu_run_value_writes_its_flag(tmp_path: Path, scan: ScanContext) -> None:
    registry = FakeRegistry({(Hive.HKCU, RUN): [SYNC]})
    auto = autostart("windows", tmp_path, registry)
    value_id = only_id(scan, auto)

    preview = run(["autostart", "disable", value_id], scan, auto)
    done = run(["autostart", "disable", value_id, "--yes"], scan, auto)

    assert preview[1] == (
        "Would disable Sync (run_key, user):\n"
        f"  location: HKCU\\{RUN}\\Sync\n"
        "  its StartupApproved flag is set to disabled, as the Task Manager does; the Run value"
        " is never written\n"
        "Nothing was changed. Re-run with --yes to disable it.\n"
    )
    assert done == (0, "Disabled Sync (change 1).\n", "")
    ((key, value),) = registry.writes
    assert (key, value.name, value.kind) == (APPROVED, "Sync", ValueKind.REG_BINARY)
    assert isinstance(value.data, bytes)
    assert value.data[:4] == b"\x03\x00\x00\x00"


def test_enable_preview_of_a_run_value(tmp_path: Path, scan: ScanContext) -> None:
    flag = RegValue("Sync", ValueKind.REG_BINARY, b"\x03" + bytes(11))
    auto = autostart(
        "windows", tmp_path, FakeRegistry({(Hive.HKCU, RUN): [SYNC], (Hive.HKCU, APPROVED): [flag]})
    )

    _, out, _ = run(["autostart", "enable", only_id(scan, auto)], scan, auto)

    assert "  its StartupApproved flag is set to enabled; the Run value is never written\n" in out


def test_a_read_only_entry_is_refused(tmp_path: Path, scan: ScanContext, data_dir: Path) -> None:
    once = RegValue("Setup", ValueKind.REG_SZ, r"C:\setup.exe")
    auto = autostart("windows", tmp_path, FakeRegistry({(Hive.HKCU, RUN_ONCE): [once]}))

    code, out, _ = run(["autostart", "disable", only_id(scan, auto), "--yes"], scan, auto)

    assert (code, out) == (1, "Refused: run_once_key entries are read-only.\n")
    assert rows(data_dir) == []


def test_nothing_can_be_changed_on_macos(tmp_path: Path, scan: ScanContext, data_dir: Path) -> None:
    agent = {
        "Label": "com.example.agent",
        "ProgramArguments": ["/usr/bin/agent"],
        "RunAtLoad": True,
    }
    # home and root are both tmp_path here: a daemon is listed once, an agent twice
    write(tmp_path / "Library" / "LaunchDaemons" / "agent.plist", plistlib.dumps(agent))
    auto = autostart("darwin", tmp_path)

    code, out, _ = run(["autostart", "disable", only_id(scan, auto), "--yes"], scan, auto)

    assert (code, out) == (1, "Refused: launch_agent entries are read-only.\n")
    assert rows(data_dir) == []


def test_a_rolled_back_write_is_shown(tmp_path: Path, scan: ScanContext) -> None:
    error = RegistryError("Access is denied")
    registry = FakeRegistry({(Hive.HKCU, RUN): [SYNC]}, write_error=error)
    auto = autostart("windows", tmp_path, registry)

    code, out, _ = run(["autostart", "disable", only_id(scan, auto), "--yes"], scan, auto)

    assert (code, out) == (1, "Not changed: Access is denied; it was rolled back (change 1).\n")


def test_a_failed_change_says_how_to_recover(
    tmp_path: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(self: RunKeyChanges, item: AutostartItem) -> ChangeResult:
        return ChangeResult(7, ChangeState.FAILED, None, "the flag is something else")

    monkeypatch.setattr(RunKeyChanges, "disable", failed)
    auto = autostart("windows", tmp_path, FakeRegistry({(Hive.HKCU, RUN): [SYNC]}))

    code, out, err = run(["autostart", "disable", only_id(scan, auto), "--yes"], scan, auto)

    assert (code, out) == (3, "")
    assert err == (
        "safeclean: change 7 failed: the flag is something else;"
        " run 'safeclean autostart recover'\n"
    )


def test_a_flag_that_cannot_be_read_back_stops_with_the_reason(
    tmp_path: Path, scan: ScanContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreadable(self: RunKeyChanges, item: AutostartItem) -> ChangeResult:
        raise RegistryError("access denied")

    monkeypatch.setattr(RunKeyChanges, "disable", unreadable)
    auto = autostart("windows", tmp_path, FakeRegistry({(Hive.HKCU, RUN): [SYNC]}))

    code, _, err = run(["autostart", "disable", only_id(scan, auto), "--yes"], scan, auto)

    assert code == 3
    assert err == (
        "safeclean: an unfinished autostart change cannot be checked: access denied; fix or move"
        " what is there, then run 'safeclean autostart recover' again\n"
    )
