import tomllib
from pathlib import Path

import safeclean

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_exposed() -> None:
    assert safeclean.__version__ == "0.0.1"


def test_a_warning_fails_the_tests() -> None:
    # pre-step-8 audit, A3: a deprecation fails the gate when it is announced, not when the
    # dependency removes what it deprecated
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["pytest"]["ini_options"]["filterwarnings"] == ["error"]
