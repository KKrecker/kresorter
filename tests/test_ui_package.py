"""The extra, the entry points, starting without PySide6, and CI (decision 0014, items 8-10).

These tests need no Qt: the launch is imported, and its window only when Qt is there.
"""

import importlib
import inspect
import runpy
import sys
import tomllib
from pathlib import Path

import pytest

from kresorter.autostart.listing import AutostartContext
from kresorter.core.scanner import ScanContext
from kresorter.environment import Environment
from kresorter.ui import launch

ROOT = Path(__file__).resolve().parents[1]
QT = "PySide6-Essentials>=6.8,<7"


def project() -> dict[str, object]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    found = data["project"]
    assert isinstance(found, dict)
    return found


def test_the_extra_and_the_dev_dependencies() -> None:
    # [0014.8]
    extras = project()["optional-dependencies"]
    assert isinstance(extras, dict)
    assert extras["ui"] == [QT]
    assert any(name.startswith("PySide6-Essentials==") for name in extras["dev"])
    assert any(name.startswith("pytest-qt==") for name in extras["dev"])
    assert project()["dependencies"] == []


def test_the_entry_points() -> None:
    # [0014.8]
    assert project()["gui-scripts"] == {"kresorter-ui": "kresorter.ui.launch:main"}
    assert project()["scripts"] == {"kresorter": "kresorter.cli:main"}


def test_main_takes_its_arguments_and_an_environment() -> None:
    # [0014.8]
    parameters = inspect.signature(launch.main).parameters
    assert list(parameters) == ["argv", "environment"]
    assert parameters["argv"].default is None
    assert parameters["environment"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["environment"].default is None


def test_python_dash_m_runs_the_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    # [0014.8]
    calls: list[tuple[object, ...]] = []

    def launched(*args: object) -> int:
        calls.append(args)
        return 7

    monkeypatch.setattr(launch, "main", launched)
    with pytest.raises(SystemExit) as exited:
        runpy.run_module("kresorter.ui", run_name="__main__")

    assert (exited.value.code, calls) == (7, [()])


def no_scan() -> ScanContext:
    raise AssertionError("nothing is made without Qt")


def no_autostart() -> AutostartContext:
    raise AssertionError("nothing is made without Qt")


UNTOUCHED = Environment(scan_context=no_scan, autostart_context=no_autostart)


@pytest.mark.usefixtures("without_qt")
def test_without_pyside6_one_line_and_exit_3(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # [0014.9]
    assert launch.main([], environment=UNTOUCHED) == 3

    captured = capsys.readouterr()
    assert captured.out == ""
    line, end = captured.err.split("\n")
    assert end == ""
    assert line.startswith(
        'kresorter-ui: the desktop window needs PySide6 (pip install "kresorter[ui]"): '
    )
    assert "PySide6" in line.removeprefix("kresorter-ui: the desktop window needs PySide6")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.usefixtures("without_qt")
def test_without_pyside6_the_default_environment_is_not_made(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0014.9]
    monkeypatch.setattr(launch, "Environment", no_environment)

    assert launch.main() == 3
    assert capsys.readouterr().err.count("\n") == 1


def no_environment() -> Environment:
    raise AssertionError("no environment without Qt")


@pytest.mark.usefixtures("qt_without_its_library")
def test_a_library_qt_cannot_load_is_one_line_and_exit_3(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # [0014.9] PySide6 is there, libGL is not (pre-step-8 audit, A1)
    assert launch.main([], environment=UNTOUCHED) == 3

    captured = capsys.readouterr()
    assert captured.out == ""
    line, end = captured.err.split("\n")
    assert end == ""
    assert line.startswith("kresorter-ui: Qt cannot load a library it needs (libGL.so.1: ")
    assert all(library in line for library in LIBRARIES)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.usefixtures("without_qt")
def test_without_a_standard_error_nothing_is_written_and_exit_3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0014.9] a GUI script on Windows runs without one (pre-step-8 audit, A1)
    monkeypatch.setattr(sys, "stderr", None)

    assert launch.main([], environment=UNTOUCHED) == 3


def test_another_import_error_is_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    # [0014.9] only Qt's absence is the one line; a broken module of the window is raised
    monkeypatch.setitem(sys.modules, "kresorter.ui.app", None)
    window = importlib.import_module("kresorter.ui")
    monkeypatch.delattr(window, "app", raising=False)

    with pytest.raises(ImportError, match=r"kresorter\.ui\.app"):
        launch.main([], environment=UNTOUCHED)


# --- CI ------------------------------------------------------------------------------------------

LIBRARIES = ("libegl1", "libgl1", "libxkbcommon0", "libfontconfig1", "libdbus-1-3")


def workflow() -> str:
    return (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_ci_installs_qt_s_libraries_before_the_package() -> None:
    # [0014.10]
    lines = workflow().splitlines()
    (apt,) = [i for i, line in enumerate(lines) if "apt-get install" in line]
    (pip,) = [i for i, line in enumerate(lines) if "pip install" in line]
    assert apt < pip
    assert all(library in lines[apt].split() for library in LIBRARIES)
    assert '".[dev]"' in lines[pip]


def test_ci_runs_the_window_offscreen_on_every_python() -> None:
    # [0014.10]
    text = workflow()
    assert "QT_QPA_PLATFORM: offscreen" in text
    assert 'python-version: ["3.11", "3.12", "3.13", "3.14"]' in text
    assert "run: pytest" in text


def test_the_tests_set_the_offscreen_platform() -> None:
    # [0014.10] locally too, before the application is made
    conftest = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")' in conftest
