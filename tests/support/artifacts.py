"""The wheel and the sdist, built once per run, offline, into a temporary folder (decision 0015).

``python -m build --no-isolation`` makes the sdist from the repository, then the wheel from the
sdist, with the ``hatchling`` of the running Python: nothing is downloaded. ``wheel_from_tree``
makes a second wheel straight from the repository, to compare with the first.
"""

import email.message
import email.parser
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
