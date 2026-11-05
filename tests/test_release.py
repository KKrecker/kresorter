"""The release job's checks and files (decision 0015, items 23 and 28): ``packaging/release.py``.

``check TAG`` passes when the tag is ``v`` and ``__version__``, that version is the changelog's
latest, and ``docs/releases/<version>.md`` records the runs on clean machines: Windows 10 and
Windows 11 with the installer and the portable zip, an Ubuntu LTS with pipx, each run saying
what was done and seen; otherwise it fails, before anything is published. ``notes TAG`` is that
version's section of the changelog, the GitHub release's text; ``sums FOLDER...`` is
``SHA256SUMS.txt``, one line per file in the form ``sha256sum --check`` reads. Here each runs
on a made-up repository; the real tag is CI's, and the real record the owner's.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
import release
import winbuild

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


SEEN = (
    "- **The window on a screen**: it opened at 1920 x 1080, in English.\n"
    "- **A scan**: Scan now on the safe zones, 41 findings.\n"
    "- **A file quarantined and restored**: `old.iso` moved, then put back\n"
    "  where it was.\n"
    "- **Each page**: each of the six shown.\n"
    "- **A folder sorted and its batch undone**: Downloads sorted, then undone.\n"
    "- **The uninstall**: the program gone, the data directory still there.\n"
)
RECORD = f"""\
# Kresorter 1.2.3 on clean machines

## Windows 10 22H2

- **System**: Windows 10 Pro 22H2, build 19045.
- **Installed**: `Kresorter-1.2.3-setup.exe`, then `Kresorter-1.2.3-portable.zip` unzipped.
{SEEN}
## Windows 11 24H2

- **System**: Windows 11 Home 24H2, build 26100.
- **Installed**: `Kresorter-1.2.3-setup.exe`, then `Kresorter-1.2.3-portable.zip` unzipped.
{SEEN}
## Ubuntu 24.04 LTS

- **System**: Ubuntu 24.04.3 LTS, GNOME on Wayland.
- **Installed**: `pipx install "kresorter[ui]"`, Python 3.12.
{SEEN}"""
LABELS = (
    "System",
    "Installed",
    "The window on a screen",
    "A scan",
    "A file quarantined and restored",
    "Each page",
    "A folder sorted and its batch undone",
    "The uninstall",
)


def repository(
    tmp_path: Path,
    version: str = "1.2.3",
    changelog: str = CHANGELOG,
    record: str | None = RECORD,
) -> Path:
    root = tmp_path / "repository"
    package = root / "src" / "kresorter"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        f'"""kresorter."""\n\n__version__ = "{version}"  # the only place\n', encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    if record is not None:
        (root / "docs" / "releases").mkdir(parents=True)
        (root / "docs" / "releases" / f"{version}.md").write_text(record, encoding="utf-8")
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
        "v1.2.3: __version__ and the changelog's latest version are 1.2.3\n"
        "docs/releases/1.2.3.md: the runs on Windows 10 22H2, Windows 11 24H2, Ubuntu 24.04 LTS\n",
        "",
    )


def test_the_changelog_dated_the_day_of_the_tag_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0019.18] the day the release job is given: that of the tagged commit
    root = repository(tmp_path)

    assert release.main(["check", "v1.2.3", "--day", "2026-01-31"], root) == 0

    assert capsys.readouterr().out.splitlines()[:2] == [
        "v1.2.3: __version__ and the changelog's latest version are 1.2.3",
        "CHANGELOG.md: 1.2.3 is dated 2026-01-31, the day of the tag",
    ]


@pytest.mark.parametrize("day", ["2026-02-01", "2026-01-30", "31.01.2026"])
def test_a_changelog_dated_another_day_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], day: str
) -> None:
    # [0019.18] before the record is looked at, and before anything is published
    root = repository(tmp_path, record=None)

    assert release.main(["check", "v1.2.3", "--day", day], root) == 1

    assert capsys.readouterr() == (
        "",
        f"check: the changelog dates 1.2.3 2026-01-31, not {day}, the day of the tag\n",
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


def test_without_the_record_of_the_version_the_tag_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0015.28] the record comes from the owner's runs, before the tag
    root = repository(tmp_path, record=None)
    (root / "docs" / "releases").mkdir(parents=True)
    (root / "docs" / "releases" / "1.2.2.md").write_text(RECORD, encoding="utf-8")

    assert release.main(["check", "v1.2.3"], root) == 1

    assert capsys.readouterr() == (
        "",
        "check: no docs/releases/1.2.3.md, the record of the runs on clean machines\n",
    )


def without(record: str, heading: str) -> str:
    """``record`` without the run under ``heading``."""
    start = record.index(f"## {heading}\n")
    end = record.find("\n## ", start + 1)
    return record[:start] + (record[end + 1 :] if end >= 0 else "")


@pytest.mark.parametrize(
    ("heading", "system"),
    [
        ("Windows 10 22H2", "Windows 10"),
        ("Windows 11 24H2", "Windows 11"),
        ("Ubuntu 24.04 LTS", "an Ubuntu LTS"),
    ],
)
def test_a_record_without_a_system_s_run_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], heading: str, system: str
) -> None:
    # [0015.28] Windows 10, Windows 11 and an Ubuntu LTS
    root = repository(tmp_path, record=without(RECORD, heading))

    assert release.main(["check", "v1.2.3"], root) == 1

    assert capsys.readouterr().err == (
        f"check: the record of 1.2.3 is not complete: no run on {system}\n"
    )


@pytest.mark.parametrize(
    ("heading", "other", "system"),
    [
        ("Ubuntu 24.04 LTS", "Ubuntu 24.10", "an Ubuntu LTS"),
        ("Ubuntu 24.04 LTS", "Ubuntu LTS", "an Ubuntu LTS"),
        ("Ubuntu 24.04 LTS", "Debian 12", "an Ubuntu LTS"),
        ("Windows 10 22H2", "Windows 100", "Windows 10"),
        ("Windows 10 22H2", "Windows 8.1", "Windows 10"),
        ("Windows 11 24H2", "Windows Server 2022", "Windows 11"),
    ],
)
def test_a_run_on_another_system_is_not_one_of_them(heading: str, other: str, system: str) -> None:
    # [0015.28] an Ubuntu LTS has its version, a Windows its number
    text = RECORD.replace(f"## {heading}\n", f"## {other}\n")

    with pytest.raises(release.ReleaseError) as refused:
        release.record("1.2.3", text)

    assert str(refused.value) == f"the record of 1.2.3 is not complete: no run on {system}"


@pytest.mark.parametrize("label", LABELS[2:])
def test_each_run_says_what_was_done_and_seen(label: str) -> None:
    # [0015.28] the window on a screen, a scan, a file quarantined and restored, each page, a
    # folder sorted and its batch undone, the uninstall: missing in one run, empty in another
    line = next(line for line in SEEN.splitlines() if line.startswith(f"- **{label}**:"))
    windows, ubuntu = RECORD.split("## Ubuntu")
    text = (
        windows.replace(line + "\n", "", 1)
        + "## Ubuntu"
        + ubuntu.replace(line, f"- **{label}**:   ")
    )
    if label == "A file quarantined and restored":
        text = text.replace(f"- **{label}**:   \n  where it was.", f"- **{label}**:")

    with pytest.raises(release.ReleaseError) as refused:
        release.record("1.2.3", text)

    assert str(refused.value) == (
        "the record of 1.2.3 is not complete: "
        f"Windows 10 22H2: nothing under {label!r}; Ubuntu 24.04 LTS: nothing under {label!r}"
    )


@pytest.mark.parametrize("label", LABELS[:2])
def test_each_run_says_the_system_and_how_it_was_installed(label: str) -> None:
    # [0015.28] the system and its version, and how it was installed, which then names nothing
    windows, ubuntu = RECORD.split("## Windows 11")
    line = next(line for line in windows.splitlines() if line.startswith(f"- **{label}**:"))
    text = windows.replace(line, f"- **{label}**:") + "## Windows 11" + ubuntu

    with pytest.raises(release.ReleaseError) as refused:
        release.record("1.2.3", text)

    assert str(refused.value) == (
        f"the record of 1.2.3 is not complete: Windows 10 22H2: nothing under {label!r}"
    )


@pytest.mark.parametrize(
    ("old", "new", "said"),
    [
        (
            "`Kresorter-1.2.3-setup.exe`, then ",
            "",
            "Windows 10 22H2: 'Installed' names no Kresorter-1.2.3-setup.exe",
        ),
        (
            ", then `Kresorter-1.2.3-portable.zip` unzipped",
            "",
            "Windows 10 22H2: 'Installed' names no Kresorter-1.2.3-portable.zip",
        ),
        (
            "Kresorter-1.2.3-portable.zip",
            "Kresorter-1.2.2-portable.zip",
            "Windows 10 22H2: 'Installed' names no Kresorter-1.2.3-portable.zip",
        ),
    ],
)
def test_on_windows_the_installer_and_the_portable_zip_of_the_version(
    old: str, new: str, said: str
) -> None:
    # [0015.28]
    windows, rest = RECORD.split("## Windows 11")
    text = windows.replace(old, new) + "## Windows 11" + rest

    with pytest.raises(release.ReleaseError) as refused:
        release.record("1.2.3", text)

    assert str(refused.value) == f"the record of 1.2.3 is not complete: {said}"


def test_on_ubuntu_pipx() -> None:
    # [0015.28]
    text = RECORD.replace('`pipx install "kresorter[ui]"`', '`pip install "kresorter[ui]"`')

    with pytest.raises(release.ReleaseError) as refused:
        release.record("1.2.3", text)

    assert str(refused.value) == (
        "the record of 1.2.3 is not complete: Ubuntu 24.04 LTS: 'Installed' names no pipx"
    )


def test_every_gap_is_said_at_once() -> None:
    # [0015.28] the owner fills them all in one go
    text = without(without(RECORD, "Windows 10 22H2"), "Ubuntu 24.04 LTS").replace(
        "- **The uninstall**: the program gone, the data directory still there.\n", ""
    )

    with pytest.raises(release.ReleaseError) as refused:
        release.record("1.2.3", text)

    assert str(refused.value) == (
        "the record of 1.2.3 is not complete: no run on Windows 10; "
        "Windows 11 24H2: nothing under 'The uninstall'; no run on an Ubuntu LTS"
    )


def template() -> str:
    """The record's form in ``docs/releases/README.md``: its one ``markdown`` block."""
    text = (ROOT / "docs" / "releases" / "README.md").read_text(encoding="utf-8")
    (block,) = re.findall(r"^```markdown\n(.*?)^```$", text, flags=re.MULTILINE | re.DOTALL)
    return str(block)


def test_the_form_has_a_line_for_each_thing_the_record_says() -> None:
    # [0015.28] the owner copies it to docs/releases/<version>.md and fills it
    form = template()
    assert release.LABELS == LABELS
    for system in ("Windows 10", "Windows 11", "Ubuntu 24.04 LTS"):
        assert f"\n## {system}\n" in form, system
    assert form.count("- **") == 3 * len(LABELS)
    with pytest.raises(release.ReleaseError, match=r"nothing under 'System'"):
        release.record("1.2.3", form.replace("X.Y.Z", "1.2.3"))


def test_the_form_filled_in_is_a_record() -> None:
    # [0015.28]
    filled = re.sub(r"^(- \*\*.+\*\*:)$", r"\1 done.", template(), flags=re.MULTILINE)

    assert release.record("1.2.3", filled.replace("X.Y.Z", "1.2.3")) == [
        "Windows 10",
        "Windows 11",
        "Ubuntu 24.04 LTS",
    ]


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


# --- the first release [0019.18] ----------------------------------------------------------------


def test_the_first_release_is_0_1_0_wherever_its_version_is_written() -> None:
    # [0019.18] __version__, which names the files and makes the version resources of
    # Kresorter.exe and of the installer, and the changelog's latest heading
    source = (ROOT / "src" / "kresorter" / "__init__.py").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert kresorter.__version__ == "0.1.0"
    assert release.check("v0.1.0", source, changelog) == "0.1.0"
    assert re.search(r"^## \[0\.1\.0\] - \d{4}-\d{2}-\d{2}$", changelog, re.MULTILINE)
    assert [name.format(version="0.1.0") for name in release.WINDOWS] == [
        "Kresorter-0.1.0-setup.exe",
        "Kresorter-0.1.0-portable.zip",
    ]
    resource = winbuild.version_text()
    for said in (
        "filevers=(0, 1, 0, 0)",
        "prodvers=(0, 1, 0, 0)",
        "StringStruct('FileVersion', '0.1.0')",
        "StringStruct('ProductVersion', '0.1.0')",
    ):
        assert said in resource
