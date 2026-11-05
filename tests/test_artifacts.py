"""The wheel and the sdist (decision 0015, items 8, 9 and 21).

One wheel for every system, with the package and nothing else; an sdist with what makes that
wheel, and the wheel it makes is the one the repository makes. In CI's build job they are the
ones it built and keeps, named by ``KRESORTER_DIST``.
"""

import configparser
import zipfile
from pathlib import Path

import pytest

from support.artifacts import (
    ROOT,
    Built,
    built_for_the_run,
    sdist_files,
    wheel_files,
    wheel_from_tree,
)

DIST_INFO = "kresorter-0.1.0.dist-info/"
SDIST = {
    "src",
    "tests",
    "docs",
    "README.md",
    "README.ru.md",
    "CHANGELOG.md",
    "LICENSE",
    "pyproject.toml",
}


def package_files() -> list[str]:
    """The files of ``src/kresorter``, as the wheel names them; no bytecode."""
    source = ROOT / "src"
    return sorted(
        path.relative_to(source).as_posix()
        for path in (source / "kresorter").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )


def contents(wheel: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(wheel) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_one_wheel_for_every_system(built: Built) -> None:
    # [0015.8]
    assert built.wheel.name == "kresorter-0.1.0-py3-none-any.whl"
    wheel = contents(built.wheel)[DIST_INFO + "WHEEL"].decode("utf-8").splitlines()
    assert "Root-Is-Purelib: true" in wheel
    assert "Tag: py3-none-any" in wheel


def test_the_wheel_has_the_package_and_nothing_else(built: Built) -> None:
    # [0015.8] the modules, py.typed, the tables, the icons and their licence
    files = wheel_files(built.wheel)
    package = [name for name in files if not name.startswith(DIST_INFO)]
    assert package == package_files()
    assert {"kresorter/py.typed", "kresorter/ui/icons/LICENSE"} <= set(package)
    assert sorted(name.removeprefix(DIST_INFO) for name in files if name.startswith(DIST_INFO)) == [
        "METADATA",
        "RECORD",
        "WHEEL",
        "entry_points.txt",
        "licenses/LICENSE",
        "licenses/src/kresorter/ui/icons/LICENSE",
    ]


def test_its_entry_points_are_the_two_commands(built: Built) -> None:
    # [0015.8] those of 0014 item 8
    points = configparser.ConfigParser()
    points.read_string(contents(built.wheel)[DIST_INFO + "entry_points.txt"].decode("utf-8"))
    assert {section: dict(points[section]) for section in points.sections()} == {
        "console_scripts": {"kresorter": "kresorter.cli:main"},
        "gui_scripts": {"kresorter-ui": "kresorter.ui.launch:main"},
    }


def test_the_sdist_has_what_makes_the_wheel_and_nothing_else(built: Built) -> None:
    # [0015.9]
    files = sdist_files(built.sdist)
    assert {name.split("/")[0] for name in files} == SDIST | {"PKG-INFO", ".gitignore"}
    assert not [name for name in files if "__pycache__" in name or name.endswith(".pyc")]
    assert built.sdist.name == "kresorter-0.1.0.tar.gz"


def test_the_sdist_makes_the_wheel_the_repository_makes(built: Built, tmp_path: Path) -> None:
    # [0015.9] the same files, byte for byte
    assert contents(built.wheel) == contents(wheel_from_tree(tmp_path))


def test_ci_s_build_job_checks_the_ones_it_built(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # [0015.21] nothing is built when KRESORTER_DIST names the folder
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "kresorter-0.1.0.tar.gz").write_bytes(b"sdist")
    (dist / "kresorter-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
    monkeypatch.setenv("KRESORTER_DIST", str(dist))
    out = tmp_path / "out"
    out.mkdir()

    found = built_for_the_run(out)

    assert found == Built(
        dist / "kresorter-0.1.0.tar.gz", dist / "kresorter-0.1.0-py3-none-any.whl"
    )
    assert list(out.iterdir()) == []
