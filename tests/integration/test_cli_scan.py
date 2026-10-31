"""`safeclean scan`: end-to-end on a real temporary tree. The disk must not change."""

import io
import json
import runpy
import sys
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy
from safeclean import cli
from safeclean.core.heuristics import JunkClassifier, Platform, default_rules
from safeclean.core.scanner import ScanContext


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


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
    )


def snapshot(root: Path) -> list[tuple[str, int, int, bytes]]:
    return sorted(
        (str(p), p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes())
        for p in root.rglob("*")
        if p.is_file()
    )


def run(args: list[str], context: ScanContext) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(args, out=out, context_factory=lambda: context)
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
    assert cli.detect_platform(sys_platform) == expected


def test_unsupported_platform_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="unsupported platform"):
        cli.detect_platform("sunos5")


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_default_context_posix(tmp_path: Path, platform: Platform) -> None:
    context = cli.default_context(platform=platform, env={}, home=tmp_path)

    assert context.policy.default_roots() == (tmp_path / ".cache", tmp_path / "Downloads")
    assert context.open_files_checked is False
    assert context.open_files.is_open(tmp_path) is False


def test_default_context_windows() -> None:
    env = {"USERPROFILE": r"C:\Users\Alice"}
    context = cli.default_context(platform="windows", env=env, home=Path("/unused"))

    assert [str(p) for p in context.policy.default_roots()] == [
        r"C:\Users\Alice\.cache",
        r"C:\Users\Alice\Downloads",
    ]


def test_default_context_uses_current_system() -> None:
    context = cli.default_context()

    assert context.policy.default_roots()[0].name == ".cache"


def test_python_dash_m_entry_point(
    tmp_path: Path, tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "default_context", lambda: ctx(tmp_path, tree))
    monkeypatch.setattr(sys, "argv", ["safeclean", "scan", "--json", str(tree)])
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("safeclean", run_name="__main__")

    assert exc.value.code == 0
    assert json.loads(out.getvalue())["files_scanned"] == 4
    assert tree.is_dir()
