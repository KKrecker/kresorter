"""What CI built, run (decision 0015, item 22): ``packaging/trial.py``, with a fake machine.

``python packaging/trial.py KIND DIST`` runs the wheel, the portable zip or the installer of
``DIST``. A trial starts every program through one runner; here a fake one stands for the new
virtual environment, pip, the commands, the installer and the uninstaller, and makes what each
would make. Each trial passes on what it should see and fails, saying why, on each thing it
checks; the real runs are CI's.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

import pytest
import trial

from kresorter.core.policy import PathPolicy
from kresorter.ui.window import PAGES

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"
SILENT = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]


@dataclass
class Machine:
    """A fake runner: what each program would do, and every command it was given."""

    local: Path  # LOCALAPPDATA
    commands: list[list[str]] = field(default_factory=list)
    shown_version: str = f"kresorter {VERSION}\n"
    report: str = trial.REPORT
    failing: Path | None = None  # the program that exits with 1
    makes_data: bool = True  # the self-test makes the data directory, as every session does
    writes_beside: bool = False  # the self-test writes a file beside the program
    installs: bool = True
    uninstalls: bool = True
    takes_data: bool = False  # the uninstall takes the data directory with it
    leaving: Path | None = None  # the folder the uninstaller is removing, from another process
    slept: float = 0.0

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = list(command)
        self.commands.append(command)
        program = Path(command[0])
        if program == self.failing:
            return subprocess.CompletedProcess(command, 1, "", "it went wrong\n")
        stdout = ""
        if command[1:] == ["--version"]:
            stdout = self.shown_version
        elif command[1:2] == ["--self-test"]:
            Path(command[2]).write_text(self.report, encoding="utf-8")
            if self.makes_data:
                (self.local / trial.DATA).mkdir(parents=True, exist_ok=True)
            if self.writes_beside:
                (program.parent / "written.txt").write_text("x", encoding="utf-8")
        elif program.name.endswith("-setup.exe") and self.installs:
            folder = self.local / "Programs" / trial.NAME
            (folder / "_internal").mkdir(parents=True)
            (folder / trial.EXE).write_bytes(b"MZ")
            (folder / "unins000.exe").write_bytes(b"MZ")
        elif program.name.startswith("unins") and self.uninstalls:
            self.leaving = program.parent
        return subprocess.CompletedProcess(command, 0, stdout, "")

    def sleep(self, seconds: float) -> None:
        """The uninstaller, relaunched from a temporary copy, is done after two seconds."""
        self.slept += seconds
        if self.leaving is not None and self.slept >= 2:
            self.leaving.rename(self.local / "removed")
            if self.takes_data:
                (self.local / trial.DATA).rename(self.local / "data-removed")
            self.leaving = None


@pytest.fixture
def machine(tmp_path: Path) -> Machine:
    local = tmp_path / "local"
    local.mkdir()
    return Machine(local)


@pytest.fixture
def work(tmp_path: Path) -> Path:
    found = tmp_path / "work"
    found.mkdir()
    return found


def dist_with(tmp_path: Path, *names: str) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    for name in names:
        (dist / name).write_bytes(b"built")
    return dist


WHEEL = f"kresorter-{VERSION}-py3-none-any.whl"
ZIP = f"Kresorter-{VERSION}-portable.zip"
SETUP = f"Kresorter-{VERSION}-setup.exe"


def test_a_report_is_one_line_per_page_in_the_window_s_order() -> None:
    # [0015.22] the self-test's report (item 17), which trial.py cannot import: no Qt there
    assert trial.PAGES == PAGES
    assert "".join(f"{page}: shown\n" for page in PAGES) == trial.REPORT


def test_it_looks_where_windows_puts_the_installed_folder_and_the_data() -> None:
    # [0015.22] {userpf} for the current user, and kresorter's data directory
    local = PureWindowsPath(r"C:\Users\a\AppData\Local")
    policy = PathPolicy.for_windows({"LOCALAPPDATA": str(local), "USERPROFILE": r"C:\Users\a"})
    assert policy.app_data_dir == local / trial.DATA
    iss = (ROOT / "packaging" / "windows" / "kresorter.iss").read_text(encoding="utf-8")
    assert f"DefaultDirName={{userpf}}\\{trial.NAME}" in iss.splitlines()
    assert ("Kresorter.exe" if os.name == "nt" else "Kresorter") == trial.EXE


# --- the wheel -----------------------------------------------------------------------------------


def test_the_wheel_is_installed_with_the_extra_ui_then_shows_its_version_and_self_tests(
    tmp_path: Path, machine: Machine, work: Path
) -> None:
    # [0015.22] in a new virtual environment
    dist = dist_with(tmp_path, WHEEL, f"kresorter-{VERSION}.tar.gz")

    trial.wheel(dist, work, machine)

    env = work / "wheel"
    assert machine.commands == [
        [sys.executable, "-m", "venv", str(env)],
        [
            str(trial.script(env, "python")),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            f"{dist / WHEEL}[ui]",
        ],
        [str(trial.script(env, "kresorter")), "--version"],
        [str(trial.script(env, "kresorter-ui")), "--self-test", str(work / "wheel-report.txt")],
    ]


def test_a_script_is_where_the_environment_keeps_it(tmp_path: Path) -> None:
    # [0015.22]
    if os.name == "nt":
        assert trial.script(tmp_path, "kresorter") == tmp_path / "Scripts" / "kresorter.exe"
    else:
        assert trial.script(tmp_path, "kresorter") == tmp_path / "bin" / "kresorter"


def test_another_version_fails(tmp_path: Path, machine: Machine, work: Path) -> None:
    # [0015.22] the version is the wheel's
    machine.shown_version = "kresorter 0.0.9\n"
    dist = dist_with(tmp_path, WHEEL)

    with pytest.raises(trial.TrialFailed, match=r"kresorter --version: 'kresorter 0\.0\.9\\n'"):
        trial.wheel(dist, work, machine)


def test_a_program_that_fails_fails_the_trial_with_its_output(
    tmp_path: Path, machine: Machine, work: Path
) -> None:
    # [0015.22]
    machine.failing = trial.script(work / "wheel", "python")
    dist = dist_with(tmp_path, WHEEL)

    with pytest.raises(trial.TrialFailed, match=r"exited with 1\nit went wrong") as failed:
        trial.wheel(dist, work, machine)

    assert "pip install" in str(failed.value)
    assert len(machine.commands) == 2


@pytest.mark.parametrize(
    "report",
    ["overview: shown\n", "".join(f"{page}: shown\n" for page in reversed(PAGES)), ""],
)
def test_a_self_test_without_every_page_shown_in_order_fails(
    tmp_path: Path, machine: Machine, work: Path, report: str
) -> None:
    # [0015.22]
    machine.report = report
    dist = dist_with(tmp_path, WHEEL)

    with pytest.raises(trial.TrialFailed, match=r"--self-test: the report is"):
        trial.wheel(dist, work, machine)


def test_a_self_test_that_writes_no_report_fails(
    tmp_path: Path, machine: Machine, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0015.22]
    def silent(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if "--self-test" in command:
            return subprocess.CompletedProcess(list(command), 0, "", "")
        return machine(command)

    dist = dist_with(tmp_path, WHEEL)

    with pytest.raises(trial.TrialFailed, match=r"--self-test: no report"):
        trial.wheel(dist, work, silent)


@pytest.mark.parametrize("names", [(), (WHEEL, "kresorter-0.2.0-py3-none-any.whl")])
def test_not_one_wheel_fails(
    tmp_path: Path, machine: Machine, work: Path, names: tuple[str, ...]
) -> None:
    # [0015.22]
    dist = dist_with(tmp_path, *names)

    with pytest.raises(trial.TrialFailed, match=rf"{len(names)} files kresorter-\*\.whl"):
        trial.wheel(dist, work, machine)
    assert machine.commands == []


# --- the portable zip ----------------------------------------------------------------------------


def portable_zip(dist: Path, *names: str) -> Path:
    dist.mkdir(exist_ok=True)
    made = dist / ZIP
    with zipfile.ZipFile(made, "w") as archive:
        for name in names:
            archive.writestr(name, b"built")
    return made


def test_the_unzipped_folder_self_tests_and_is_left_as_it_was(
    tmp_path: Path, machine: Machine, work: Path
) -> None:
    # [0015.22]
    dist = tmp_path / "dist"
    portable_zip(dist, f"Kresorter/{trial.EXE}", "Kresorter/_internal/base_library.zip")

    trial.portable(dist, work, machine)

    program = work / "portable" / "Kresorter" / trial.EXE
    assert machine.commands == [[str(program), "--self-test", str(work / "portable-report.txt")]]
    assert (work / "portable" / "Kresorter" / "_internal" / "base_library.zip").is_file()


def test_a_zip_without_the_program_fails(tmp_path: Path, machine: Machine, work: Path) -> None:
    # [0015.22]
    dist = tmp_path / "dist"
    portable_zip(dist, f"Other/{trial.EXE}", "Other/_internal/base_library.zip")

    with pytest.raises(trial.TrialFailed, match=rf"{ZIP}: no Kresorter/{trial.EXE}"):
        trial.portable(dist, work, machine)
    assert machine.commands == []


def test_a_self_test_that_writes_in_the_portable_folder_fails(
    tmp_path: Path, machine: Machine, work: Path
) -> None:
    # [0015.22] its data go to the data directory, as the installed one's
    machine.writes_beside = True
    dist = tmp_path / "dist"
    portable_zip(dist, f"Kresorter/{trial.EXE}")

    with pytest.raises(trial.TrialFailed, match=r"the self-test changed the portable folder"):
        trial.portable(dist, work, machine)


# --- the installer -------------------------------------------------------------------------------


def install(dist: Path, work: Path, machine: Machine, patience: float = trial.PATIENCE) -> None:
    """The installer's trial on the fake machine, whose LOCALAPPDATA is its own."""
    trial.installer(
        dist,
        work,
        machine,
        environ={"LOCALAPPDATA": str(machine.local)},
        sleep=machine.sleep,
        patience=patience,
    )


def test_installed_silently_for_the_current_user_then_self_tested_then_uninstalled(
    tmp_path: Path, machine: Machine, work: Path
) -> None:
    # [0015.22] the uninstaller relaunches itself: its folder is waited for
    dist = dist_with(tmp_path, SETUP)
    folder = machine.local / "Programs" / "Kresorter"

    install(dist, work, machine)

    assert machine.commands == [
        [str(dist / SETUP), *SILENT, f"/LOG={work / 'setup.log'}"],
        [str(folder / trial.EXE), "--self-test", str(work / "installed-report.txt")],
        [str(folder / "unins000.exe"), *SILENT, f"/LOG={work / 'uninstall.log'}"],
    ]
    assert not folder.exists()
    assert (machine.local / "kresorter").is_dir()
    assert machine.slept == 2


def test_an_installer_that_installs_nothing_fails(
    tmp_path: Path, machine: Machine, work: Path
) -> None:
    # [0015.22]
    machine.installs = False
    dist = dist_with(tmp_path, SETUP)

    with pytest.raises(trial.TrialFailed, match=rf"{SETUP} installed no .*{trial.EXE}"):
        install(dist, work, machine)


def test_no_data_directory_after_the_self_test_fails(
    tmp_path: Path, machine: Machine, work: Path
) -> None:
    # [0015.22] the data directory the uninstall must keep
    machine.makes_data = False
    dist = dist_with(tmp_path, SETUP)

    with pytest.raises(trial.TrialFailed, match=r"no data directory .* after the self-test"):
        install(dist, work, machine)
    assert len(machine.commands) == 2


def test_a_folder_still_there_after_the_uninstall_fails(
    tmp_path: Path, machine: Machine, work: Path
) -> None:
    # [0015.22]
    machine.uninstalls = False
    dist = dist_with(tmp_path, SETUP)

    with pytest.raises(trial.TrialFailed, match=r"still there 5 s after the uninstall"):
        install(dist, work, machine, patience=5)
    assert machine.slept == 5


def test_an_uninstall_that_takes_the_data_fails(
    tmp_path: Path, machine: Machine, work: Path
) -> None:
    # [0015.22]
    machine.takes_data = True
    dist = dist_with(tmp_path, SETUP)

    with pytest.raises(trial.TrialFailed, match=r"the uninstall removed the data directory"):
        install(dist, work, machine)


# --- the command ---------------------------------------------------------------------------------


def test_the_command_runs_one_trial_in_a_temporary_folder(
    tmp_path: Path, machine: Machine, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0015.22]
    dist = dist_with(tmp_path, WHEEL)

    assert trial.main(["wheel", str(dist)], machine) == 0

    (venv,) = [command for command in machine.commands if command[1:3] == ["-m", "venv"]]
    work = Path(venv[3]).parent
    assert not work.exists()
    assert tmp_path not in work.parents
    assert capsys.readouterr() == ("wheel: passed\n", "")


def test_a_failed_trial_is_exit_1_and_says_why(
    tmp_path: Path,
    machine: Machine,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0015.22]
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    dist = dist_with(tmp_path)

    assert trial.main(["wheel", str(dist)], machine) == 1

    assert capsys.readouterr() == ("", f"wheel: {dist}: 0 files kresorter-*.whl\n")


def test_on_github_a_failed_trial_is_an_annotation_of_the_job_too(
    tmp_path: Path,
    machine: Machine,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0015.20] which GitHub shows without signing in, unlike the job's log
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    dist = dist_with(tmp_path)

    assert trial.main(["wheel", str(dist)], machine) == 1

    why = f"wheel: {dist}: 0 files kresorter-*.whl"
    assert capsys.readouterr() == (f"::error title=trial.py wheel::{why}\n", why + "\n")


def test_an_annotation_is_one_line_of_ascii() -> None:
    # [0015.20] a workflow command is one line; Windows' runners write in the code page
    failed = trial.TrialFailed("50%\r\nit went wrong \u00b7")
    assert trial.annotation("portable", failed) == (
        r"::error title=trial.py portable::portable: 50%25%0D%0Ait went wrong \xb7"
    )


def test_the_command_knows_three_trials(capsys: pytest.CaptureFixture[str]) -> None:
    # [0015.22]
    assert list(trial.TRIALS) == ["wheel", "portable", "installer"]
    with pytest.raises(SystemExit) as stopped:
        trial.main(["sdist", "dist"])
    assert stopped.value.code == 2
    assert "invalid choice: 'sdist'" in capsys.readouterr().err


def test_the_runner_runs_a_program_and_hands_over_its_code_and_output() -> None:
    # [0015.22] the trial, not the runner, decides what an exit code means
    done = trial.run([sys.executable, "-c", "print('out'); raise SystemExit(3)"])

    assert (done.returncode, done.stdout) == (3, "out\n")
