"""`kresorter scan`: end-to-end on a real temporary tree. The disk must not change."""

import io
import json
import runpy
import sys
from pathlib import Path

import pytest

import kresorter
from fakes import FakeOpenFiles, make_policy
from kresorter import cli, environment
from kresorter.core.heuristics import JunkClassifier, Platform, default_rules
from kresorter.core.policy import BlockReason, Verdict
from kresorter.core.scanner import ScanContext
from kresorter.environment import Environment
from support.files import snapshot, write


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    write(root / "proj" / "__pycache__" / "m.cpython-313.pyc", b"bytecode")
    write(root / "photos" / "img.jpg", b"jpeg-bytes")
    write(root / "backup" / "img.jpg", b"jpeg-bytes")
    write(root / "notes.txt", b"hello")
    write(root / "blocked" / "keep.txt", b"never listed")
    return root


def ctx(tmp_path: Path, tree: Path, *, checked: bool = True) -> ScanContext:
    # tmp_path lives under /tmp, which the real "posix-temp" rule (rightly) marks as junk.
    # Drop that one rule so the test sees the tree's own junk, not its location.
    rules = [r for r in default_rules() if r.id != "posix-temp"]
    return ScanContext(
        policy=make_policy(tmp_path, tree / "blocked", default_roots=[tree]),
        open_files=FakeOpenFiles(),
        classifier=JunkClassifier(rules, platform="linux"),
        open_files_checked=checked,
        platform="linux",
    )


def run(args: list[str], context: ScanContext) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(args, out=out, environment=Environment(scan_context=lambda: context))
    return code, out.getvalue()


def test_text_report(tmp_path: Path, tree: Path) -> None:
    code, out = run(["scan", str(tree)], ctx(tmp_path, tree))

    assert code == 0
    assert "report only, nothing was changed" in out
    assert "Scanned: 4 files, 33 B" in out
    assert "Junk candidates: 1 file, 8 B" in out
    assert "[python-bytecode]" in out
    assert "Duplicate groups: 1 (wasted 10 B)" in out
    assert str(tree / "photos" / "img.jpg") in out
    assert f"blocked (system): {tree / 'blocked'}" in out
    assert "open-file check" not in out


def test_json_report(tmp_path: Path, tree: Path) -> None:
    code, out = run(["scan", "--json", str(tree)], ctx(tmp_path, tree))
    data = json.loads(out)

    assert code == 0
    assert data["roots"] == [str(tree)]
    assert data["files_scanned"] == 4
    assert data["bytes_scanned"] == 33
    assert data["open_file_check"] is True
    assert data["junk"] == [
        {
            "path": str(tree / "proj" / "__pycache__" / "m.cpython-313.pyc"),
            "rule_id": "python-bytecode",
            "category": "cache",
            "size": 8,
        }
    ]
    assert data["duplicates"][0]["size"] == 10
    assert data["duplicates"][0]["paths"] == [
        str(tree / "backup" / "img.jpg"),
        str(tree / "photos" / "img.jpg"),
    ]
    assert data["skipped"] == [
        {"path": str(tree / "blocked"), "reason": "blocked", "block_reason": "system", "detail": ""}
    ]


def test_no_hash_flag(tmp_path: Path, tree: Path) -> None:
    _, out = run(["scan", "--json", "--no-hash", str(tree)], ctx(tmp_path, tree))

    assert json.loads(out)["duplicates"] == []


def test_without_paths_scans_default_roots(tmp_path: Path, tree: Path) -> None:
    _, out = run(["scan", "--json"], ctx(tmp_path, tree))

    assert json.loads(out)["roots"] == [str(tree)]


def test_missing_path_is_reported_not_fatal(tmp_path: Path, tree: Path) -> None:
    code, out = run(["scan", str(tmp_path / "nope")], ctx(tmp_path, tree))

    assert code == 0
    assert f"not_found: {tmp_path / 'nope'}" in out


def test_unchecked_open_files_are_disclosed(tmp_path: Path, tree: Path) -> None:
    _, out = run(["scan", str(tree)], ctx(tmp_path, tree, checked=False))

    assert "open-file check is not available yet" in out


def test_scan_never_modifies_the_disk(tmp_path: Path, tree: Path) -> None:
    before = snapshot(tmp_path)

    run(["scan", str(tree)], ctx(tmp_path, tree))
    run(["scan", "--json", str(tree)], ctx(tmp_path, tree))

    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("args", [[], ["clean"], ["scan", "--bogus"]])
def test_bad_usage_exits_with_2(tmp_path: Path, tree: Path, args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        run(args, ctx(tmp_path, tree))

    assert exc.value.code == 2


@pytest.mark.parametrize(
    ("size", "text"),
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.0 KiB"),
        (1536, "1.5 KiB"),
        (5 * 1024**2, "5.0 MiB"),
        (3 * 1024**3, "3.0 GiB"),
        (2 * 1024**4, "2.0 TiB"),
        (2048 * 1024**4, "2048.0 TiB"),
    ],
)
def test_format_size(size: int, text: str) -> None:
    assert cli.format_size(size) == text


@pytest.mark.parametrize(
    ("sys_platform", "expected"),
    [("win32", "windows"), ("linux", "linux"), ("darwin", "darwin")],
)
def test_detect_platform(sys_platform: str, expected: str) -> None:
    assert environment.detect_platform(sys_platform) == expected


def test_unsupported_platform_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="unsupported platform"):
        environment.detect_platform("sunos5")


def test_explicit_scan_never_lists_the_app_data_dir(tmp_path: Path, tree: Path) -> None:
    # Even when the user scans a parent of the data dir (e.g. ~), the vault stays invisible.
    app_data = tree / "appdata" / "kresorter"
    write(app_data / "quarantine" / "1" / "1" / "m.cpython-313.pyc", b"in vault")
    base = ctx(tmp_path, tree)
    context = ScanContext(
        policy=make_policy(tmp_path, tree / "blocked", default_roots=[tree], app_data_dir=app_data),
        open_files=base.open_files,
        classifier=base.classifier,
        open_files_checked=True,
        platform="linux",
    )
    _, out = run(["scan", "--json", str(tree)], context)
    data = json.loads(out)

    assert all(not item["path"].startswith(str(app_data)) for item in data["junk"])
    assert {
        "path": str(app_data),
        "reason": "blocked",
        "block_reason": "app_data",
        "detail": "",
    } in data["skipped"]


def test_default_context_passes_environment_to_posix_policy(tmp_path: Path) -> None:
    env = {"XDG_DATA_HOME": str(tmp_path / "xdg")}
    context = environment.default_context(platform="linux", env=env, home=tmp_path)

    assert context.policy.app_data_dir == tmp_path / "xdg" / "kresorter"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_default_context_posix(tmp_path: Path, platform: Platform) -> None:
    context = environment.default_context(platform=platform, env={}, home=tmp_path)

    assert context.policy.default_roots() == (tmp_path / ".cache", tmp_path / "Downloads")
    assert context.policy.app_data_dir.name == "kresorter"


def test_default_context_windows() -> None:
    env = {"USERPROFILE": r"C:\Users\Alice"}
    context = environment.default_context(platform="windows", env=env, home=Path("/unused"))

    assert [str(p) for p in context.policy.default_roots()] == [
        r"C:\Users\Alice\.cache",
        r"C:\Users\Alice\Downloads",
    ]


def test_default_context_uses_current_system() -> None:
    context = environment.default_context()

    assert context.policy.default_roots()[0].name == ".cache"


PACKAGE = Path(kresorter.__file__).resolve().parent


def test_the_folders_kresorter_runs_from(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # [0015.16] the package's folder; frozen (Kresorter.exe), the executable's too
    assert environment.program_folders() == (PACKAGE,)
    executable = tmp_path / "Kresorter" / "Kresorter.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    assert environment.program_folders() == (PACKAGE, executable.parent.resolve())


def test_the_running_system_s_context_blocks_kresorter_s_own_folder(tmp_path: Path) -> None:
    # [0015.16] whatever the profile
    for context in (
        environment.default_context(),
        environment.default_context(environment.detect_platform(), {}, tmp_path),
    ):
        verdict = context.policy.check_path(PACKAGE / "__pycache__" / "cli.cpython-313.pyc")
        assert verdict == Verdict(allowed=False, reason=BlockReason.APP_PROGRAM)


def test_python_dash_m_entry_point(
    tmp_path: Path, tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(environment, "default_context", lambda: ctx(tmp_path, tree))
    monkeypatch.setattr(sys, "argv", ["kresorter", "scan", "--json", str(tree)])
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("kresorter", run_name="__main__")

    assert exc.value.code == 0
    assert json.loads(out.getvalue())["files_scanned"] == 4
    assert tree.is_dir()
