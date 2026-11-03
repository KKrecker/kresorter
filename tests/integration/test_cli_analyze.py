"""`kresorter analyze`: end-to-end on a real temporary tree. Read-only, like `scan`."""

import io
import json
import os
import time
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy
from kresorter import cli
from kresorter.analysis.duplicates import KeepReason
from kresorter.core.heuristics import JunkClassifier, default_rules
from kresorter.core.scanner import ScanContext
from kresorter.environment import Environment
from support.files import snapshot

DAY_NS = 86_400 * 10**9
MIB = 1024**2


def write(path: Path, data: bytes, *, days_ago: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    stamp = time.time_ns() - days_ago * DAY_NS
    os.utime(path, ns=(stamp, stamp))
    return path


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    write(root / "proj" / "__pycache__" / "m.cpython-313.pyc", b"bytecode")
    write(root / "photos" / "img.jpg", b"jpeg-bytes", days_ago=10)  # older copy: kept
    write(root / "backup" / "img.jpg", b"jpeg-bytes", days_ago=5)
    write(root / "notes.txt", b"hello")
    write(root / "media" / "big.bin", b"x" * (MIB + 1))
    write(root / "archive" / "letter.txt", b"dear", days_ago=40)
    write(root / "blocked" / "keep.txt", b"never listed")
    return root


def ctx(tmp_path: Path, tree: Path, *, checked: bool = True) -> ScanContext:
    # Same as test_cli_scan: drop "posix-temp", which would flag all of tmp_path as junk.
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


def section(out: str, title: str) -> list[str]:
    """The lines of one report section: from its title up to the next blank line."""
    lines = [*out.splitlines(), ""]
    start = next(i for i, line in enumerate(lines) if line.startswith(title))
    return lines[start : lines.index("", start)]


def test_text_report_groups_findings_by_level(tmp_path: Path, tree: Path) -> None:
    code, out = run(["analyze", str(tree)], ctx(tmp_path, tree))
    pyc = tree / "proj" / "__pycache__" / "m.cpython-313.pyc"

    assert code == 0
    assert out.startswith("kresorter analyze - report only, nothing was changed\n")
    assert "Scanned: 6 files" in out
    assert section(out, "Safe:") == [
        "Safe: 1 file, 8 B",
        f"  {pyc}  8 B",
        "    junk_cache: python-bytecode",
    ]
    assert section(out, "Likely safe:") == [
        "Likely safe: 1 file, 10 B",
        f"  {tree / 'backup' / 'img.jpg'}  10 B",
        f"    duplicate_copy: {tree / 'photos' / 'img.jpg'}",
    ]
    assert section(out, "Review (never proposed):") == ["Review (never proposed): 0 files, 0 B"]
    assert "Proposed for quarantine: 2 files, 18 B" in out
    assert f"blocked (system): {tree / 'blocked'}" in out


def test_thresholds_from_the_command_line(tmp_path: Path, tree: Path) -> None:
    args = ["analyze", "--large", "1", "--older-than", "30", str(tree)]
    _, out = run(args, ctx(tmp_path, tree))

    assert section(out, "Review (never proposed):") == [
        "Review (never proposed): 2 files, 1.0 MiB",
        f"  {tree / 'media' / 'big.bin'}  1.0 MiB",
        "    large: 1.0 MiB",
        f"  {tree / 'archive' / 'letter.txt'}  4 B",
        "    old: unmodified for 40 days",
    ]
    assert "Proposed for quarantine: 2 files, 18 B" in out


def test_a_kept_copy_is_shown_but_never_proposed(tmp_path: Path, tree: Path) -> None:
    kept = write(tree / "a" / "__pycache__" / "x.pyc", b"same", days_ago=9)
    copy = write(tree / "b" / "__pycache__" / "x.pyc", b"same", days_ago=3)

    _, out = run(["analyze", str(tree)], ctx(tmp_path, tree))
    safe = section(out, "Safe:")

    assert f"  {kept}  4 B  (kept copy, not proposed)" in safe
    assert f"  {copy}  4 B" in safe
    assert f"    duplicate_copy: {kept}" in safe
    assert "Proposed for quarantine: 3 files, 22 B" in out


def test_json_report(tmp_path: Path, tree: Path) -> None:
    code, out = run(["analyze", "--json", str(tree)], ctx(tmp_path, tree))
    data = json.loads(out)
    keeper, copy = tree / "photos" / "img.jpg", tree / "backup" / "img.jpg"

    assert code == 0
    assert data["roots"] == [str(tree)]
    assert data["files_scanned"] == 6
    assert data["open_file_check"] is True
    assert data["thresholds"] == {"large_bytes": 500 * MIB, "old_after_days": 730}
    assert data["findings"][0]["twin"] is None
    assert data["findings"][1] == {
        "path": str(copy),
        "size": 10,
        "level": "likely_safe",
        "proposed": True,
        "kept_copy": False,
        "twin": str(keeper),
        "reasons": [{"evidence": "duplicate_copy", "detail": str(keeper)}],
    }
    assert data["duplicates"] == [
        {
            "digest": data["duplicates"][0]["digest"],
            "keep": str(keeper),
            "keep_reason": str(KeepReason.OLDEST),
            "remove": [str(copy)],
        }
    ]
    assert data["totals"] == [
        {"level": "safe", "files": 1, "bytes": 8},
        {"level": "likely_safe", "files": 1, "bytes": 10},
        {"level": "review", "files": 0, "bytes": 0},
    ]
    assert data["proposed"] == {"files": 2, "bytes": 18}
    assert data["skipped"][0]["path"] == str(tree / "blocked")


def test_json_marks_a_kept_copy(tmp_path: Path, tree: Path) -> None:
    kept = write(tree / "a" / "__pycache__" / "x.pyc", b"same", days_ago=9)
    write(tree / "b" / "__pycache__" / "x.pyc", b"same", days_ago=3)

    _, out = run(["analyze", "--json", str(tree)], ctx(tmp_path, tree))
    found = {f["path"]: f for f in json.loads(out)["findings"]}

    assert found[str(kept)]["proposed"] is False
    assert found[str(kept)]["kept_copy"] is True


def test_relative_roots_are_reported_with_absolute_paths(
    tmp_path: Path, tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    _, out = run(["analyze", "root"], ctx(tmp_path, tree))

    assert f"  {tree / 'backup' / 'img.jpg'}  10 B" in out
    assert f"    duplicate_copy: {tree / 'photos' / 'img.jpg'}" in out


def test_without_paths_analyzes_default_roots(tmp_path: Path, tree: Path) -> None:
    _, out = run(["analyze"], ctx(tmp_path, tree))

    assert f"Roots: {tree}" in out


def test_nothing_found_is_not_an_error(tmp_path: Path, tree: Path) -> None:
    clean = write(tmp_path / "clean" / "notes.txt", b"hello").parent

    code, out = run(["analyze", str(clean)], ctx(tmp_path, tree))

    assert code == 0
    assert "Proposed for quarantine: 0 files, 0 B" in out


def test_unchecked_open_files_are_disclosed(tmp_path: Path, tree: Path) -> None:
    _, out = run(["analyze", str(tree)], ctx(tmp_path, tree, checked=False))

    assert "open-file check is not available yet" in out


def test_analyze_never_modifies_the_disk(tmp_path: Path, tree: Path) -> None:
    before = snapshot(tmp_path)

    run(["analyze", str(tree)], ctx(tmp_path, tree))
    run(["analyze", "--json", "--large", "1", "--older-than", "1", str(tree)], ctx(tmp_path, tree))

    assert snapshot(tmp_path) == before
    assert not (tmp_path / "appdata").exists()


@pytest.mark.parametrize(
    ("args", "option"),
    [
        (["analyze", "--large", "0"], "--large"),
        (["analyze", "--large", "-1"], "--large"),
        (["analyze", "--large", "1.5"], "--large"),
        (["analyze", "--older-than", "0"], "--older-than"),
        (["analyze", "--older-than", "many"], "--older-than"),
        (["analyze", "--no-hash"], "--no-hash"),
    ],
)
def test_bad_usage_exits_with_2(
    tmp_path: Path, tree: Path, capsys: pytest.CaptureFixture[str], args: list[str], option: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(args, ctx(tmp_path, tree))

    assert exc.value.code == 2
    assert option in capsys.readouterr().err
