import tomllib
from pathlib import Path

import kresorter

ROOT = Path(__file__).resolve().parents[1]


def test_the_version_is_written_once() -> None:
    # [0015.2] in the package; pyproject.toml reads it from there and has none of its own
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert kresorter.__version__ == "0.1.0"
    assert "version" not in project["project"]
    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["hatch"]["version"] == {"path": "src/kresorter/__init__.py"}


def test_a_warning_fails_the_tests() -> None:
    # pre-step-8 audit, A3: a deprecation fails the gate when it is announced, not when the
    # dependency removes what it deprecated
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["pytest"]["ini_options"]["filterwarnings"] == ["error"]


def test_a_hung_test_shows_where_it_waits() -> None:
    # CI run 42003708808: a test still running after two minutes has every thread's stack
    # written out, so the log of a hang says where it waits
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["pytest"]["ini_options"]["faulthandler_timeout"] == 120
