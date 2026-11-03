"""The release job's checks and files (decision 0015, item 23): ``packaging/release.py``.

``check TAG`` passes when the tag is ``v`` and ``__version__``, and that version is the
changelog's latest; otherwise it fails, before anything is published. ``notes TAG`` is that
version's section of the changelog, the GitHub release's text; ``sums FOLDER...`` is
``SHA256SUMS.txt``, one line per file in the form ``sha256sum --check`` reads. Here each runs
on a made-up repository; the real tag is CI's.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import release

import kresorter

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = """\
# Changelog

## [Unreleased]

### Fixed
- Not released yet.

## [1.2.3] - 2026-01-31

### Added
- `kresorter scan`: what it finds.

### Fixed
- The window's title.

## [1.2.2] - 2025-12-01

### Added
- The first one.
"""


def repository(tmp_path: Path, version: str = "1.2.3", changelog: str = CHANGELOG) -> Path:
    root = tmp_path / "repository"
    package = root / "src" / "kresorter"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        f'"""kresorter."""\n\n__version__ = "{version}"  # the only place\n', encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return root


def test_the_version_is_read_where_it_is_written() -> None:
    # [0015.23] the release job installs nothing: the version is read, not imported
    assert release.ROOT == ROOT
    source = (ROOT / "src" / "kresorter" / "__init__.py").read_text(encoding="utf-8")
    assert release.version(source) == kresorter.__version__


def test_a_source_without_the_version_is_refused() -> None:
    # [0015.23]
    with pytest.raises(release.ReleaseError, match=r"no __version__"):
        release.version('"""kresorter."""\nVERSION = "1.2.3"\n')


def test_the_tag_of_the_version_and_the_changelog_s_latest_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0015.23]
    root = repository(tmp_path)

    assert release.main(["check", "v1.2.3"], root) == 0

    assert capsys.readouterr() == (
        "v1.2.3: __version__ and the changelog's latest version are 1.2.3\n",
        "",
    )


@pytest.mark.parametrize("tag", ["v1.2.2", "1.2.3", "v1.2.3-rc1", "v1.2.3 "])
def test_another_tag_fails_before_anything_is_published(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], tag: str
) -> None:
    # [0015.23]
    root = repository(tmp_path)

    assert release.main(["check", tag], root) == 1

    assert capsys.readouterr() == ("", f"check: the tag {tag!r} is not 'v1.2.3' (__version__)\n")


def test_a_version_the_changelog_does_not_end_with_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0015.23] __version__ moved on and the changelog did not, or the other way round
    root = repository(tmp_path, version="1.2.4")

    assert release.main(["check", "v1.2.4"], root) == 1

    assert capsys.readouterr().err == (
        "check: the changelog's latest version is 1.2.3, not 1.2.4 (__version__)\n"
    )


@pytest.mark.parametrize(
    "changelog",
    [
        "# Changelog\n\n## [Unreleased]\n\n### Added\n- Something.\n",
        "# Changelog\n\n## [1.2.3]\n\n### Added\n- No date.\n",
        "# Changelog\n\n## 1.2.3 - 2026-01-31\n\n### Added\n- No brackets.\n",
    ],
)
def test_a_changelog_without_a_dated_version_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], changelog: str
) -> None:
    # [0015.23] the latest version is the first heading ## [X.Y.Z] - YYYY-MM-DD
    root = repository(tmp_path, changelog=changelog)

    assert release.main(["check", "v1.2.3"], root) == 1

    assert capsys.readouterr().err == "check: the changelog has no version yet\n"


def test_the_notes_are_the_version_s_section_of_the_changelog(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0015.23] without its heading and without what is unreleased
    root = repository(tmp_path)

    assert release.main(["notes", "v1.2.3"], root) == 0

    assert capsys.readouterr().out == (
        "### Added\n- `kresorter scan`: what it finds.\n\n### Fixed\n- The window's title.\n"
    )


def test_the_notes_of_an_older_version_end_at_the_changelog_s_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0015.23]
    root = repository(tmp_path)

    assert release.main(["notes", "v1.2.2"], root) == 0

    assert capsys.readouterr().out == "### Added\n- The first one.\n"


def test_no_notes_for_a_version_the_changelog_does_not_have(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0015.23]
    root = repository(tmp_path)

    assert release.main(["notes", "v9.9.9"], root) == 1

    assert capsys.readouterr() == ("", "notes: the changelog has no section 9.9.9\n")


def test_the_sums_are_one_line_per_file_sorted_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0015.23] what is published, from both folders; the form sha256sum --check reads
    dist, windows = tmp_path / "dist", tmp_path / "windows"
    dist.mkdir()
    windows.mkdir()
    files = {
        dist / "kresorter-1.2.3-py3-none-any.whl": b"wheel",
        dist / "kresorter-1.2.3.tar.gz": b"sdist",
        windows / "Kresorter-1.2.3-portable.zip": b"zip",
        windows / "Kresorter-1.2.3-setup.exe": b"setup",
    }
    for path, content in files.items():
        path.write_bytes(content)

    assert release.main(["sums", str(dist), str(windows)], tmp_path) == 0

    names = [
        "Kresorter-1.2.3-portable.zip",
        "Kresorter-1.2.3-setup.exe",
        "kresorter-1.2.3-py3-none-any.whl",
        "kresorter-1.2.3.tar.gz",
    ]
    by_name = {path.name: content for path, content in files.items()}
    assert capsys.readouterr().out == "".join(
        f"{hashlib.sha256(by_name[name]).hexdigest()}  {name}\n" for name in names
    )


def test_two_files_of_one_name_have_no_sum(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0015.23] the release would have only one of them
    one, other = tmp_path / "one", tmp_path / "other"
    for folder in (one, other):
        folder.mkdir()
        (folder / "same.txt").write_bytes(folder.name.encode())

    assert release.main(["sums", str(one), str(other)], tmp_path) == 1

    assert capsys.readouterr() == ("", "sums: two files are named same.txt\n")


def test_the_command_knows_three_steps(capsys: pytest.CaptureFixture[str]) -> None:
    # [0015.23]
    with pytest.raises(SystemExit) as stopped:
        release.main(["publish", "v1.2.3"])
    assert stopped.value.code == 2
    assert "invalid choice: 'publish'" in capsys.readouterr().err
