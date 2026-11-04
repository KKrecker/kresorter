"""What CI built, run (decision 0015, item 22): ``python packaging/trial.py KIND DIST``.

``wheel``: the wheel of ``DIST`` in a new virtual environment with the extra ``ui``, then
``kresorter --version`` and the self-test of ``kresorter-ui`` (item 17). On Windows,
``portable``: the zip unzipped, the self-test of its ``Kresorter.exe``, which leaves the folder
as it was; ``installer``: run silently for the current user, the self-test of the installed
``Kresorter.exe``, then the silent uninstall, after which the installed folder is gone and the
data directory is still there. Every program is started by one runner, which the tests replace.
On GitHub a failed trial is an annotation of the job too, which anyone can read, unlike its log.
The Python that runs this has no Kresorter and no Qt: what it needs of them is written here.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

__all__ = [
    "DATA",
    "EXE",
    "NAME",
    "PAGES",
    "PATIENCE",
    "REPORT",
    "TRIALS",
    "Runner",
    "TrialFailed",
    "annotation",
    "installer",
    "main",
    "portable",
    "run",
    "script",
    "wheel",
]

NAME = "Kresorter"
EXE = f"{NAME}.exe" if os.name == "nt" else NAME
DATA = "kresorter"  # the data directory's name in LOCALAPPDATA
PAGES = ("overview", "findings", "organize", "autostart", "quarantine", "settings")
REPORT = "".join(f"{page}: shown\n" for page in PAGES)  # the self-test's, when it passes
SILENT = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
PATIENCE = 120.0  # seconds the uninstaller, relaunched from a temporary copy, has to finish
TIMEOUT = 600  # seconds a program has, a self-test or an installation

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class TrialFailed(Exception):
    """What a trial did not see; its message says what."""


def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """``command`` run to its end, with its exit code and output; the trial checks them."""
    return subprocess.run(
        list(command), capture_output=True, text=True, check=False, timeout=TIMEOUT
    )


def checked(runner: Runner, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    done = runner(command)
    if done.returncode != 0:
        shown = " ".join(command)
        raise TrialFailed(f"{shown} exited with {done.returncode}\n{done.stdout}{done.stderr}")
    return done


def one(folder: Path, pattern: str) -> Path:
    found = sorted(folder.glob(pattern))
    if len(found) != 1:
        raise TrialFailed(f"{folder}: {len(found)} files {pattern}")
    return found[0]


def script(env: Path, name: str) -> Path:
    """A command of the virtual environment ``env``."""
    if os.name == "nt":
        return env / "Scripts" / f"{name}.exe"
    return env / "bin" / name


def self_test(runner: Runner, program: Path, report: Path) -> None:
    """``program --self-test report``: exit 0 and every page shown, in the sidebar's order."""
    checked(runner, [str(program), "--self-test", str(report)])
    if not report.is_file():
        raise TrialFailed(f"{program.name} --self-test: no report")
    text = report.read_text(encoding="utf-8")
    if text != REPORT:
        raise TrialFailed(f"{program.name} --self-test: the report is {text!r}")


# --- the trials ----------------------------------------------------------------------------------


def wheel(dist: Path, work: Path, runner: Runner = run) -> None:
    """The wheel with the extra ``ui`` in a new virtual environment: its version, its window."""
    found = one(dist, "kresorter-*.whl")
    version = found.name.split("-")[1]
    env = work / "wheel"
    checked(runner, [sys.executable, "-m", "venv", str(env)])
    python = str(script(env, "python"))
    checked(runner, [python, "-m", "pip", "install", "--disable-pip-version-check", f"{found}[ui]"])
    shown = checked(runner, [str(script(env, "kresorter")), "--version"]).stdout
    if shown != f"kresorter {version}\n":
        raise TrialFailed(f"kresorter --version: {shown!r}, not 'kresorter {version}'")
    self_test(runner, script(env, "kresorter-ui"), work / "wheel-report.txt")


def listing(folder: Path) -> list[tuple[str, int]]:
    """Every file and folder in ``folder``, with each file's size."""
    return sorted(
        (path.relative_to(folder).as_posix(), path.stat().st_size if path.is_file() else -1)
        for path in folder.rglob("*")
    )


def portable(dist: Path, work: Path, runner: Runner = run) -> None:
    """The portable zip unzipped and its program self-tested: nothing is written beside it."""
    found = one(dist, f"{NAME}-*-portable.zip")
    out = work / "portable"
    with zipfile.ZipFile(found) as archive:
        archive.extractall(out)
    folder = out / NAME
    program = folder / EXE
    if not program.is_file():
        raise TrialFailed(f"{found.name}: no {NAME}/{EXE}")
    before = listing(folder)
    self_test(runner, program, work / "portable-report.txt")
    if listing(folder) != before:
        raise TrialFailed("the self-test changed the portable folder")


def installer(
    dist: Path,
    work: Path,
    runner: Runner = run,
    *,
    environ: Mapping[str, str] = os.environ,
    sleep: Callable[[float], None] = time.sleep,
    patience: float = PATIENCE,
) -> None:
    """Installed silently for the current user, self-tested, uninstalled silently: the folder
    goes, the data directory stays."""
    found = one(dist, f"{NAME}-*-setup.exe")
    local = Path(environ["LOCALAPPDATA"])
    folder = local / "Programs" / NAME  # {userpf}, for the current user
    data = local / DATA
    checked(runner, [str(found), *SILENT, f"/LOG={work / 'setup.log'}"])
    program = folder / EXE
    if not program.is_file():
        raise TrialFailed(f"{found.name} installed no {program}")
    self_test(runner, program, work / "installed-report.txt")
    if not data.is_dir():
        raise TrialFailed(f"no data directory {data} after the self-test")
    uninstaller = one(folder, "unins*.exe")
    checked(runner, [str(uninstaller), *SILENT, f"/LOG={work / 'uninstall.log'}"])
    waited = 0.0
    while folder.exists():
        if waited >= patience:
            raise TrialFailed(f"{folder} still there {patience:g} s after the uninstall")
        sleep(1.0)
        waited += 1.0
    if not data.is_dir():
        raise TrialFailed(f"the uninstall removed the data directory {data}")


TRIALS: dict[str, Callable[[Path, Path, Runner], None]] = {
    "wheel": wheel,
    "portable": portable,
    "installer": installer,
}


def annotation(kind: str, failed: TrialFailed) -> str:
    """The workflow command ``::error`` saying why, which GitHub shows on the run's page without
    signing in, unlike its log: one line of ASCII, Windows' runners writing in the code page."""
    text = f"{kind}: {failed}".encode("ascii", "backslashreplace").decode("ascii")
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::error title=trial.py {kind}::{text}"


def main(argv: Sequence[str] | None = None, runner: Runner = run) -> int:
    parser = argparse.ArgumentParser(prog="trial.py", description="Run what CI built.")
    parser.add_argument("kind", choices=list(TRIALS), help="what to run")
    parser.add_argument("dist", type=Path, help="the folder it was built into")
    options = parser.parse_args(argv)
    kind: str = options.kind
    with tempfile.TemporaryDirectory(prefix="kresorter-trial-", ignore_cleanup_errors=True) as work:
        try:
            TRIALS[kind](Path(options.dist).resolve(), Path(work), runner)
        except TrialFailed as failed:
            print(f"{kind}: {failed}", file=sys.stderr)
            if os.environ.get("GITHUB_ACTIONS") == "true":
                print(annotation(kind, failed))
            return 1
    print(f"{kind}: passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
