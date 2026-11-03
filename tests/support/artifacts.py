"""The wheel and the sdist, built once per run, offline, into a temporary folder (decision 0015).

``python -m build --no-isolation`` makes the sdist from the repository, then the wheel from the
sdist, with the ``hatchling`` of the running Python: nothing is downloaded. ``wheel_from_tree``
makes a second wheel straight from the repository, to compare with the first. ``install`` puts a
wheel in a new virtual environment, offline, and ``run`` runs a command there in a profile of its
own, without the variables that would point it at the source tree.
"""

import email.message
import email.parser
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Built:
    sdist: Path
    wheel: Path  # built from the sdist


def _build(out: Path, *options: str) -> None:
    command = [sys.executable, "-m", "build", "--no-isolation", *options, "--outdir", str(out)]
    subprocess.run([*command, str(ROOT)], check=True, capture_output=True)


def build(out: Path) -> Built:
    _build(out)
    (sdist,) = out.glob("*.tar.gz")
    (wheel,) = out.glob("*.whl")
    return Built(sdist, wheel)


def wheel_from_tree(out: Path) -> Path:
    _build(out, "--wheel")
    (wheel,) = out.glob("*.whl")
    return wheel


def wheel_files(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        return sorted(archive.namelist())


def sdist_files(sdist: Path) -> list[str]:
    """The sdist's files, without the directory every one of them is in."""
    with tarfile.open(sdist) as archive:
        names = [member.name for member in archive.getmembers() if member.isfile()]
    return sorted(name.split("/", 1)[1] for name in names)


def metadata(wheel: Path) -> email.message.Message:
    with zipfile.ZipFile(wheel) as archive:
        (name,) = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        text = archive.read(name).decode("utf-8")
    return email.parser.Parser().parsestr(text)


# --- a new virtual environment -------------------------------------------------------------------


@dataclass(frozen=True)
class Venv:
    root: Path

    @property
    def bin(self) -> Path:
        return self.root / ("Scripts" if os.name == "nt" else "bin")

    def script(self, name: str) -> Path:
        return self.bin / (f"{name}.exe" if os.name == "nt" else name)

    @property
    def python(self) -> Path:
        return self.script("python")


@dataclass(frozen=True)
class Installed:
    venv: Venv
    before: frozenset[str]  # the distributions of the new environment, then with the wheel
    after: frozenset[str]


def make_venv(root: Path) -> Venv:
    """A new virtual environment with the pip its Python bundles: nothing is downloaded."""
    subprocess.run([sys.executable, "-m", "venv", str(root)], check=True, capture_output=True)
    return Venv(root)


def pip(venv: Venv, *args: str) -> subprocess.CompletedProcess[str]:
    command = [str(venv.python), "-m", "pip", "--disable-pip-version-check", *args]
    return subprocess.run(command, check=True, capture_output=True, text=True, env=clean_env())


def distributions(venv: Venv) -> frozenset[str]:
    listed = json.loads(pip(venv, "list", "--format=json").stdout)
    return frozenset(entry["name"].lower() for entry in listed)


def install(wheel: Path, root: Path) -> Installed:
    """The wheel in a new virtual environment, offline (``--no-index``)."""
    venv = make_venv(root)
    before = distributions(venv)
    pip(venv, "install", "--no-index", str(wheel))
    return Installed(venv, before, distributions(venv))


def clean_env(home: Path | None = None) -> dict[str, str]:
    """The environment without Python's or Kresorter's variables; with ``home``, a profile there:
    the home folder, and the data and configuration folders inside it."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("PYTHON", "KRESORTER", "VIRTUAL_ENV"))
    }
    if home is not None:
        env |= {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_CONFIG_HOME": str(home / "config"),
            "LOCALAPPDATA": str(home / "data"),
            "APPDATA": str(home / "config"),
        }
    return env


def data_dir(home: Path) -> Path:
    """Kresorter's data directory in the profile of ``clean_env(home)``, on either system."""
    return home / "data" / "kresorter"


def run(
    command: list[str], home: Path, extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """A command in the profile of ``home``; its exit code is the caller's to check."""
    env = clean_env(home) | (extra or {})
    return subprocess.run(command, capture_output=True, text=True, env=env, check=False)
