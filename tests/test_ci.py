"""CI (decision 0015, items 20 to 23): the checks on two systems, then the artifacts, run, and
a tag that publishes them.

The checks run on ``ubuntu-latest`` and on ``windows-latest`` for every Python of the matrix,
now that the repository is public; every push is checked, a step's branch too. Qt's system
libraries are installed on Linux only; the window's tests run offscreen on both. The checkout
is the same on both: the files keep their LF line endings on Windows.

After the checks, the build job makes the sdist, then the wheel from it, checks items 8 to 10
on them and runs the wheel; the windows job makes from that wheel the folder, the zip and the
installer and runs each (``packaging/trial.py``). Only a tag runs the release job, which checks
the tag first (``packaging/release.py``) and publishes with no token of its own.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHONS = ["3.11", "3.12", "3.13", "3.14"]
SYSTEMS = ["ubuntu-latest", "windows-latest"]
WINDOWS = set(PYTHONS)  # the repository is public


def workflow() -> list[str]:
    return (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8").splitlines()


def indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def block(lines: list[str], key: str) -> list[str]:
    """The lines under ``key:`` (the one line that is exactly it), up to the next line that is
    indented as much or less; comments and blank lines are left out."""
    lines = [line for line in lines if line.strip() and not line.strip().startswith("#")]
    (start,) = [i for i, line in enumerate(lines) if line.strip() == f"{key}:"]
    found: list[str] = []
    for line in lines[start + 1 :]:
        if indent(line) <= indent(lines[start]):
            break
        found.append(line)
    return found


def value(lines: list[str], key: str) -> str:
    """The value of ``key`` among the outermost lines of a block."""
    top = min(indent(line) for line in lines)
    (found,) = [
        line.split(":", 1)[1].strip()
        for line in lines
        if indent(line) == top and line.strip().startswith(f"{key}:")
    ]
    return found


def listed(text: str) -> list[str]:
    assert text.startswith("[")
    assert text.endswith("]")
    return [item.strip().strip('"') for item in text[1:-1].split(",")]


def combinations() -> set[tuple[str, str]]:
    """(system, Python) of every job of the check, the matrix less what it excludes."""
    matrix = block(block(workflow(), "check"), "matrix")
    systems = listed(value(matrix, "os"))
    pythons = listed(value(matrix, "python-version"))
    excluded: set[tuple[str, str]] = set()
    excludes = any(line.strip() == "exclude:" for line in matrix)
    entries = "\n".join(block(matrix, "exclude")).split("- ")[1:] if excludes else []
    for entry in entries:
        pairs = dict(re.findall(r"([a-z-]+): *\"?([^\"\n]+)\"?", entry))
        excluded.add((pairs["os"], pairs["python-version"]))
    return {(s, p) for s in systems for p in pythons} - excluded


def test_linux_and_windows_for_every_python() -> None:
    # [0015.20] Windows for the oldest and the newest only while the repository was private
    found = combinations()
    assert {p for s, p in found if s == "ubuntu-latest"} == set(PYTHONS)
    assert {p for s, p in found if s == "windows-latest"} == WINDOWS
    assert {s for s, _ in found} == set(SYSTEMS)
    assert value(block(workflow(), "check"), "runs-on") == "${{ matrix.os }}"


def test_one_failing_job_stops_no_other() -> None:
    # [0015.20] what fails on one system is seen with what fails on the other
    assert value(block(workflow(), "strategy"), "fail-fast") == "false"


def test_every_push_is_checked_a_step_s_branch_too() -> None:
    # [0015.20]
    assert [line.strip() for line in block(workflow(), "on")] == ["push:", "pull_request:"]


def test_qt_s_system_libraries_are_installed_on_linux_only() -> None:
    # [0015.20]
    lines = block(workflow(), "check")
    (apt,) = [i for i, line in enumerate(lines) if "apt-get install" in line]
    assert lines[apt - 1].strip() == "if: runner.os == 'Linux'"
    assert lines[apt - 2].strip() == "- name: Qt's system libraries"
    assert sum("if:" in line for line in lines) == 1  # every other step of the check runs on both


def test_the_window_s_tests_run_offscreen_on_both_systems() -> None:
    # [0015.20] set for the job, not for a step or a system
    job = block(workflow(), "check")
    assert value(block(job, "env"), "QT_QPA_PLATFORM") == "offscreen"


def test_the_checkout_keeps_lf_line_endings_on_windows() -> None:
    # [0015.20] a file read as bytes, hashed or packed is the same on both systems
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "* text=auto eol=lf" in attributes


# --- the artifacts, run, and the release (items 21 to 23) ---------------------------------------


def job(name: str) -> list[str]:
    return block(block(workflow(), "jobs"), name)


def step(lines: list[str], name: str) -> list[str]:
    """The lines of the step named ``name``, its first line included."""
    (start,) = [i for i, line in enumerate(lines) if line.strip() == f"- name: {name}"]
    found = [lines[start]]
    for line in lines[start + 1 :]:
        if indent(line) <= indent(lines[start]):
            break
        found.append(line)
    return found


def commands(lines: list[str]) -> list[str]:
    """What the steps run, in order: the text after each ``run:``, each line of a ``run: |``."""
    found: list[str] = []
    for index, line in enumerate(lines):
        text = line.strip().removeprefix("- ")
        if not text.startswith("run:"):
            continue
        rest = text.removeprefix("run:").strip()
        if rest != "|":
            found.append(rest)
            continue
        for inner in lines[index + 1 :]:
            if indent(inner) <= indent(line):
                break
            found.append(inner.strip())
    return found


def section(lines: list[str], key: str) -> list[str]:
    """The lines under ``key:`` among the outermost lines of ``lines``: a job's own ``env``,
    not a step's."""
    top = min(indent(line) for line in lines)
    (start,) = [
        i for i, line in enumerate(lines) if indent(line) == top and line.strip() == f"{key}:"
    ]
    found: list[str] = []
    for line in lines[start + 1 :]:
        if indent(line) <= top:
            break
        found.append(line)
    return found


def stripped(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines]


def test_the_sdist_then_the_wheel_from_it_are_built_once_after_the_checks() -> None:
    # [0015.21] on Linux, with the hatchling of the extra dev (--no-isolation); nothing else
    # builds them
    build = job("build")

    assert value(build, "needs") == "check"
    assert value(build, "runs-on") == "ubuntu-latest"
    assert "python -m build --no-isolation --outdir dist ." in commands(build)
    assert sum("python -m build" in line for line in workflow()) == 1


def test_items_8_to_10_are_checked_on_what_was_built() -> None:
    # [0015.21] the tests of the wheel and the sdist take those of the build job
    checked = step(job("build"), "Items 8 to 10, on what was built")

    assert "KRESORTER_DIST: dist" in stripped(checked)
    assert commands(checked) == [
        "pytest --no-cov -p no:cacheprovider tests/test_artifacts.py tests/test_installed.py"
    ]


def test_windows_builds_the_folder_the_zip_and_the_installer_from_that_wheel() -> None:
    # [0015.21] with the Python 3.13 of its job (item 12), PyInstaller of requirements.txt and
    # the Inno Setup pinned in the workflow (item 19)
    windows = job("windows")

    assert value(windows, "needs") == "build"
    assert value(windows, "runs-on") == "windows-latest"
    assert 'python-version: "3.13"' in stripped(windows)
    downloaded = stripped(step(windows, "The wheel and the sdist"))
    assert "uses: actions/download-artifact@v4" in downloaded
    assert "name: python-dist" in downloaded
    done = commands(windows)
    assert "python -m venv build-env" in done
    assert (
        r"build-env\Scripts\python -m pip install"
        r' "$((Get-ChildItem dist\kresorter-*.whl).FullName)[ui]"'
        r" -r packaging\windows\requirements.txt"
    ) in done
    assert r"build-env\Scripts\pyinstaller --noconfirm packaging\windows\kresorter.spec" in done
    assert (
        "choco upgrade innosetup --version $env:INNO_SETUP_VERSION -y --no-progress"
        " --allow-downgrade"
    ) in done
    assert (
        r'& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" "/DAppVersion=$version"'
        r" packaging\windows\kresorter.iss"
    ) in done
    version = [line for line in done if line.startswith("$version = ")]
    assert version == [
        r'$version = build-env\Scripts\python -c "import kresorter; print(kresorter.__version__)"'
    ]


def test_all_are_kept_as_the_run_s_artifacts() -> None:
    # [0015.21] the wheel and the sdist from Linux, the zip and the installer from Windows
    python = stripped(step(job("build"), "The wheel and the sdist, kept"))
    windows = stripped(step(job("windows"), "The portable zip and the installer, kept"))

    assert "uses: actions/upload-artifact@v4" in python
    assert {"name: python-dist", "path: dist/", "if-no-files-found: error"} <= set(python)
    assert "uses: actions/upload-artifact@v4" in windows
    assert {
        "name: windows-dist",
        "dist/Kresorter-*-portable.zip",
        "dist/Kresorter-*-setup.exe",
        "if-no-files-found: error",
    } <= set(windows)


def test_what_is_built_is_run_on_each_system() -> None:
    # [0015.22] the wheel on both, then on Windows the portable zip and the installer, each a
    # step of its own, offscreen
    build, windows = job("build"), job("windows")

    assert "python packaging/trial.py wheel dist" in commands(build)
    assert [line for line in commands(windows) if "trial.py" in line] == [
        "python packaging/trial.py wheel dist",
        "python packaging/trial.py portable dist",
        "python packaging/trial.py installer dist",
    ]
    for lines in (build, windows):
        assert value(section(lines, "env"), "QT_QPA_PLATFORM") == "offscreen"


def test_a_tag_runs_the_release_job_and_nothing_else_does() -> None:
    # [0015.23] after both builds; the only job that publishes
    release = job("release")

    assert value(release, "if") == "startsWith(github.ref, 'refs/tags/v')"
    assert value(release, "needs") == "[build, windows]"
    assert value(release, "runs-on") == "ubuntu-latest"
    for name in ("check", "build", "windows"):
        assert not any("pypi" in line or "gh release" in line for line in job(name))


def test_pypi_is_published_to_by_trusted_publishing_with_no_token() -> None:
    # [0015.23] OpenID Connect in the environment pypi; the workflow names no secret
    release = job("release")

    assert value(release, "environment") == "pypi"
    assert value(block(release, "permissions"), "id-token") == "write"
    published = stripped(step(release, "PyPI, by trusted publishing"))
    assert "uses: pypa/gh-action-pypi-publish@release/v1" in published
    assert "packages-dir: dist/" in published
    text = "\n".join(workflow())
    assert "secrets." not in text
    assert "password" not in text


def test_the_tag_is_checked_before_anything_is_published() -> None:
    # [0015.23] the tag must be __version__ and the changelog's latest version
    done = commands(job("release"))

    assert done[0] == 'python packaging/release.py check "$GITHUB_REF_NAME"'


def test_the_github_release_has_the_installer_the_zip_the_wheel_the_sdist_and_their_sums() -> None:
    # [0015.23]
    release = job("release")
    done = commands(release)

    assert "python packaging/release.py sums dist windows > SHA256SUMS.txt" in done
    assert 'python packaging/release.py notes "$GITHUB_REF_NAME" > notes.md' in done
    [created] = [line for line in done if line.startswith("gh release create")]
    assert created.split() == [
        "gh",
        "release",
        "create",
        '"$GITHUB_REF_NAME"',
        "dist/*",
        "windows/*",
        "SHA256SUMS.txt",
        "--title",
        '"Kresorter',
        '${GITHUB_REF_NAME#v}"',
        "--notes-file",
        "notes.md",
    ]
    assert value(block(release, "permissions"), "contents") == "write"
    assert "GH_TOKEN: ${{ github.token }}" in stripped(step(release, "The GitHub release"))
    downloaded = [
        line for line in stripped(release) if line.startswith("name: ") and "dist" in line
    ]
    assert downloaded == ["name: python-dist", "name: windows-dist"]
