"""The wheel installed offline in a new virtual environment, then uninstalled (decision 0015,
items 10, 11, 16 and 17).

The installed commands behave as the source tree's: the version, a scan of a made-up tree, and
the window's one line without PySide6. A scan of the environment never proposes Kresorter's own
files; with PySide6 lent to another environment, the window's self-test passes there.
Uninstalling removes every file the wheel installed and nothing of the data directory.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path

from support.artifacts import ROOT, Built, Installed, data_dir, install, pip, run
from support.cli import run as cli_run
from support.cli import scan_context

NO_QT = (
    'kresorter-ui: the desktop window needs PySide6 (pip install "kresorter[ui]"):'
    " No module named 'PySide6'\n"
)


def made_up_tree(home: Path) -> Path:
    tree = home / "tree"
    (tree / "cache").mkdir(parents=True)
    (tree / "a.txt").write_text("same", encoding="utf-8")
    (tree / "b.txt").write_text("same", encoding="utf-8")
    (tree / "Thumbs.db").write_bytes(b"\0" * 16)
    (tree / "cache" / "x.tmp").write_text("temporary", encoding="utf-8")
    return tree


def test_the_wheel_installs_nothing_else(installed: Installed) -> None:
    # [0015.10] --no-index: no network, and no dependency to fetch
    assert installed.after - installed.before == {"kresorter"}


def test_the_installed_version(installed: Installed, tmp_path: Path) -> None:
    # [0015.10]
    done = run([str(installed.venv.script("kresorter")), "--version"], tmp_path)
    assert (done.returncode, done.stdout, done.stderr) == (0, "kresorter 0.1.0\n", "")


def test_a_scan_as_from_the_source_tree(installed: Installed, tmp_path: Path) -> None:
    # [0015.10] the same report, and the installed package is the one that ran
    tree = made_up_tree(tmp_path)
    scan = ["scan", "--json", str(tree)]
    done = run([str(installed.venv.script("kresorter")), *scan], tmp_path)
    source = run([sys.executable, "-m", "kresorter", *scan], tmp_path, {"PYTHONPATH": "src"})
    assert (done.returncode, done.stderr) == (0, "")
    assert json.loads(done.stdout) == json.loads(source.stdout)
    assert json.loads(done.stdout)["files_scanned"] == 4
    where = run(
        [str(installed.venv.python), "-c", "import kresorter; print(kresorter.__file__)"], tmp_path
    )
    assert Path(where.stdout.strip()).is_relative_to(installed.venv.root)
    assert not Path(where.stdout.strip()).is_relative_to(ROOT)


def test_the_window_without_pyside6_is_one_line_and_exit_3(
    installed: Installed, tmp_path: Path
) -> None:
    # [0015.10]
    done = run([str(installed.venv.script("kresorter-ui"))], tmp_path)
    assert (done.returncode, done.stdout, done.stderr) == (3, "", NO_QT)


def paths(report: object) -> Iterator[str]:
    """Every ``path`` of a JSON report, at any depth."""
    if isinstance(report, dict):
        for key, value in report.items():
            if key == "path" and isinstance(value, str):
                yield value
            else:
                yield from paths(value)
    elif isinstance(report, list):
        for value in report:
            yield from paths(value)


def test_a_scan_of_the_environment_never_proposes_kresorter(installed: Installed) -> None:
    # [0015.16] pip compiled its bytecode, which is junk anywhere else
    package = site_packages(installed.venv.root).resolve() / "kresorter"
    assert list(package.rglob("*.pyc"))
    scan = [str(installed.venv.script("kresorter")), "scan", "--json", str(installed.venv.root)]
    done = run(scan, installed.venv.root)  # the home: beside it, it is another user's profile
    assert (done.returncode, done.stderr) == (0, "")
    report = json.loads(done.stdout)
    assert [p for p in paths(report) if Path(p).is_relative_to(package)] == [str(package)]
    skipped = {"path": str(package), "reason": "blocked", "block_reason": "app_program"}
    assert skipped | {"detail": ""} in report["skipped"]
    assert any(Path(p).name.endswith(".pyc") for p in paths(report["junk"]))  # pip's own


PAGES = ["overview", "findings", "organize", "autostart", "quarantine", "settings"]


def test_the_self_test_of_the_installed_window(
    installed_with_qt: Installed, tmp_path: Path
) -> None:
    # [0015.17] as CI runs it: offscreen, in a profile of its own; no setting is saved
    report = tmp_path / "report.txt"
    command = [str(installed_with_qt.venv.script("kresorter-ui")), "--self-test", str(report)]
    done = run(command, tmp_path, {"QT_QPA_PLATFORM": "offscreen"})
    assert done.returncode == 0, done.stderr
    assert report.read_text(encoding="utf-8").splitlines() == [f"{p}: shown" for p in PAGES]
    assert not (data_dir(tmp_path) / "settings.json").exists()


def test_uninstalling_keeps_the_user_s_data(built: Built, tmp_path: Path) -> None:
    # [0015.11] the journal, the vault with a quarantined file, the autostart store, settings.json
    installed = install(built.wheel, tmp_path / "venv")
    home = tmp_path / "home"
    downloads = home / "Downloads"
    downloads.mkdir(parents=True)
    (downloads / "old.log").write_text("quarantined", encoding="utf-8")
    data = data_dir(home)  # where the installed commands keep it in that profile
    # Quarantined by the source tree's command: under /tmp the system's own temp rule would
    # take the data directory itself for junk (support.cli.scan_context).
    code, _, err = cli_run(
        ["quarantine", "add", str(downloads / "old.log")], scan_context(home, downloads, data)
    )
    assert code == 0, err
    (data / "autostart").mkdir()
    (data / "autostart" / "agent.desktop").write_text("[Desktop Entry]\n", encoding="utf-8")
    (data / "settings.json").write_text('{"language": "ru"}', encoding="utf-8")
    kept = snapshot(data)
    assert "quarantined" in kept.values()
    record = [line.split(",")[0] for line in record_lines(installed.venv.root)]

    pip(installed.venv, "uninstall", "--yes", "kresorter")

    assert snapshot(data) == kept
    site = site_packages(installed.venv.root)
    assert [name for name in record if (site / name).exists()] == []
    assert not installed.venv.script("kresorter").exists()


def snapshot(folder: Path) -> dict[str, str]:
    """Each file under ``folder`` by its relative path, with its text (bytes as latin-1)."""
    return {
        path.relative_to(folder).as_posix(): path.read_bytes().decode("latin-1")
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def site_packages(root: Path) -> Path:
    (found,) = root.glob("lib/python3.*/site-packages") or root.glob("Lib/site-packages")
    return found


def record_lines(root: Path) -> list[str]:
    (record,) = site_packages(root).glob("kresorter-*.dist-info/RECORD")
    return record.read_text(encoding="utf-8").splitlines()
