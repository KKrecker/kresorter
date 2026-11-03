"""``kresorter --version`` (decision 0015, item 3): the version on stdout and exit 0, before
anything is read, opened or made."""

import io
import runpy
import sys

import pytest

from kresorter import cli, environment
from kresorter.autostart.listing import AutostartContext
from kresorter.core.scanner import ScanContext
from kresorter.environment import Environment

LINE = "kresorter 0.1.0\n"


def no_scan() -> ScanContext:
    raise AssertionError("--version makes no scan context")


def no_autostart() -> AutostartContext:
    raise AssertionError("--version makes no autostart context")


def test_the_version_on_stdout_and_exit_0(capsys: pytest.CaptureFixture[str]) -> None:
    # [0015.3] no context is made: no setting read, no journal opened, no data directory
    untouched = Environment(scan_context=no_scan, autostart_context=no_autostart)

    with pytest.raises(SystemExit) as exited:
        cli.main(["--version"], environment=untouched)

    assert exited.value.code == 0
    assert capsys.readouterr() == (LINE, "")


def test_python_dash_m_prints_it_too(monkeypatch: pytest.MonkeyPatch) -> None:
    # [0015.3]
    monkeypatch.setattr(environment, "default_context", no_scan)
    monkeypatch.setattr(sys, "argv", ["kresorter", "--version"])
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)

    with pytest.raises(SystemExit) as exited:
        runpy.run_module("kresorter", run_name="__main__")

    assert (exited.value.code, out.getvalue()) == (0, LINE)
