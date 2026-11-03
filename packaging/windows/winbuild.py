"""What ``kresorter.spec`` computes for the Windows application (decision 0015, items 12-14).

PyInstaller runs the spec on Windows, with the Python 3.13 of CI, in a virtual environment that
has Kresorter's wheel with the extra ``ui`` and the tools of ``requirements.txt``. The spec takes
from here the package, from that wheel (the source tree and an editable install are refused),
with its data files and every module; the icon, the sidebar's mark drawn from its SVG; the
version resource, from ``__version__``; then, once PyInstaller has made the folder, the
licences put in it and the portable zip of it. The tests run each part on any system.
"""

from __future__ import annotations

import importlib.metadata as metadata
import platform
import re
import shutil
import struct
import sys
import sysconfig
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template

from PySide6 import QtCore
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QImageWriter, QPainter

from kresorter import __version__
from kresorter.ui import icons
from kresorter.ui.theme import LIGHT

__all__ = [
    "BUNDLED",
    "NAME",
    "SCRIPT",
    "SIDES",
    "BuildError",
    "Bundled",
    "bundled",
    "datas",
    "finish",
    "hidden_imports",
    "icon",
    "installed_package",
    "licences",
    "notices",
    "portable_zip",
    "python_licence",
    "version_file",
    "version_text",
    "wheel_package",
]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = "Kresorter"
SCRIPT = HERE / "kresorter_window.py"
NOTICES = HERE / "THIRD-PARTY-NOTICES.txt"
GNU = HERE / "licenses"  # the LGPLv3 and the GPLv3 it adds to, as gnu.org has them
# What the folder carries besides Kresorter and Python, whose licence files it carries too.
BUNDLED = ("PySide6_Essentials", "shiboken6", "pyinstaller")
# Imported by name (importlib), which PyInstaller does not follow, or, for Qt's SVG module, by
# Qt itself, which draws the icons from SVG.
BY_NAME = ("ctypes", "msvcrt", "winreg", "PySide6.QtWidgets", "PySide6.QtSvg")
# The sidebar's mark (kresorter.ui.sidebar): a 28 px tile of the accent with corners of 8 px,
# the 16 px shield in its middle, in the primary button's text.
TILE, RADIUS, GLYPH, MARK = 28, 8, 16, "shield-check"
SIDES = (16, 20, 24, 32, 40, 48, 64, 256)  # those Windows shows, at each scale
DESCRIPTION = "Safe file cleanup"
AUTHOR = "KKrecker"
COPYRIGHT = "Copyright (c) 2026 KKrecker"
WHEEL_ONLY = (
    "Kresorter.exe is built from Kresorter's wheel, installed with the extra ui: pip install"
    ' "dist/kresorter-<version>-py3-none-any.whl[ui]", not the source tree or an editable'
    " install (decision 0015, item 12)"
)
_NUMBERED = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class BuildError(Exception):
    """What stops the build, and what to do."""


# --- the package, from its wheel ----------------------------------------------------------------


def installed_package(name: str = "kresorter") -> Path:
    """The folder of the package, from the wheel installed where the build runs."""
    try:
        found = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        raise BuildError(WHEEL_ONLY) from None
    return wheel_package(found)


def wheel_package(distribution: metadata.Distribution) -> Path:
    """The package's folder, which a wheel's RECORD lists and an editable install's does not."""
    modules = [f for f in distribution.files or () if f.as_posix() == "kresorter/__init__.py"]
    if not modules:
        raise BuildError(WHEEL_ONLY)
    return Path(str(distribution.locate_file(modules[0]))).parent


def datas(package: Path) -> list[tuple[str, str]]:
    """The package's files that are not modules, each with its folder in the application."""
    return [
        (str(path), str(Path(package.name, *path.parent.relative_to(package).parts)))
        for path in sorted(package.rglob("*"))
        if path.is_file() and path.suffix not in {".py", ".pyc"} and "__pycache__" not in path.parts
    ]


def hidden_imports(package: Path) -> list[str]:
    """Every module of the package, by name, then what is imported by name."""
    modules: list[str] = []
    for path in sorted(package.rglob("*.py")):
        parts = path.relative_to(package.parent).with_suffix("").parts
        modules.append(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    return [*modules, *BY_NAME]


# --- the icon -----------------------------------------------------------------------------------


def mark(side: int) -> QImage:
    """The sidebar's mark, ``side`` px square, as the sidebar draws it at 28 px."""
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    scale = side / TILE
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(LIGHT.accent))
    painter.drawRoundedRect(QRectF(0, 0, TILE, TILE), RADIUS, RADIUS)
    offset = (TILE - GLYPH) / 2
    glyph = icons.image(MARK, LIGHT.primary_text, GLYPH, scale)
    painter.drawImage(QRectF(offset, offset, GLYPH, GLYPH), glyph)
    painter.end()
    return image


def png(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    QImageWriter(buffer, QByteArray(b"png")).write(image)
    buffer.close()
    return bytes(data.data())


def ico(images: Sequence[tuple[int, bytes]]) -> bytes:
    """An ICO file of PNG images (Windows Vista and later), each with its side."""
    entries, blobs = [], []
    offset = 6 + 16 * len(images)
    for side, blob in images:
        width = 0 if side >= 256 else side  # 0 stands for 256
        entries.append(struct.pack("<BBBBHHII", width, width, 0, 0, 1, 32, len(blob), offset))
        blobs.append(blob)
        offset += len(blob)
    return struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + b"".join(blobs)


def icon(path: Path) -> Path:
    """``kresorter.ico``: the mark at each of ``SIDES``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ico([(side, png(mark(side))) for side in SIDES]))
    return path


# --- the version resource -----------------------------------------------------------------------


def version_text(version: str = __version__) -> str:
    """The version resource, as PyInstaller reads it from a file: its classes, called."""
    numbered = _NUMBERED.fullmatch(version)
    if numbered is None:
        raise BuildError(f"{version}: Windows numbers a version X.Y.Z, then 0")
    numbers = (*(int(number) for number in numbered.groups()), 0)
    named = {
        "CompanyName": AUTHOR,
        "FileDescription": DESCRIPTION,
        "FileVersion": version,
        "InternalName": NAME,
        "LegalCopyright": COPYRIGHT,
        "OriginalFilename": f"{NAME}.exe",
        "ProductName": NAME,
        "ProductVersion": version,
    }
    listed = "".join(f"        StringStruct({k!r}, {v!r}),\n" for k, v in named.items())
    return (
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers={numbers!r},\n"
        f"    prodvers={numbers!r},\n"
        "    mask=0x3F,\n"
        "    flags=0x0,\n"
        "    OS=0x40004,\n"
        "    fileType=0x1,\n"
        "    subtype=0x0,\n"
        "    date=(0, 0),\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable('040904B0', [\n"
        f"{listed}"
        "      ]),\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [0x0409, 1200])]),\n"
        "  ],\n"
        ")\n"
    )


def version_file(path: Path, version: str = __version__) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(version_text(version), encoding="utf-8")
    return path


# --- the licences -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Bundled:
    """What the folder carries besides Kresorter: the distributions whose licence files it
    has, the versions of Python and Qt, and Python's licence."""

    distributions: tuple[metadata.Distribution, ...]
    python: str
    qt: str
    python_licence: Path

    def version(self, name: str) -> str:
        found = [d.version for d in self.distributions if d.metadata["Name"] == name]
        if not found:
            raise BuildError(f"{name} is not among {BUNDLED}")
        return found[0]


def bundled(names: Sequence[str] = BUNDLED) -> Bundled:
    """``names`` as installed where the build runs, and the running Python and Qt."""
    found: list[metadata.Distribution] = []
    for name in names:
        try:
            found.append(metadata.distribution(name))
        except metadata.PackageNotFoundError:
            raise BuildError(
                f"{name} is not installed: pip install the wheel with the extra ui and"
                " -r packaging/windows/requirements.txt"
            ) from None
    candidates = (
        Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE.txt",
    )
    return Bundled(
        tuple(found), platform.python_version(), QtCore.qVersion(), python_licence(candidates)
    )


def python_licence(candidates: Iterable[Path]) -> Path:
    """The first of ``candidates`` that is a file: where Python's installation keeps it."""
    listed = list(candidates)
    for candidate in listed:
        if candidate.is_file():
            return candidate
    raise BuildError(f"Python's LICENSE.txt is in none of {[str(c) for c in listed]}")


def shipped(distribution: metadata.Distribution) -> list[tuple[Path, str]]:
    """The licence files a distribution has, each with its name in its folder: those under
    ``.dist-info/licenses`` (PEP 639), or at the top of ``.dist-info`` as older wheels have."""
    found: list[tuple[Path, str]] = []
    for file in distribution.files or ():
        parts = file.parts
        if not parts[0].endswith(".dist-info"):
            continue
        if len(parts) > 2 and parts[1] == "licenses":
            name = "/".join(parts[2:])
        elif len(parts) == 2 and parts[1].upper().startswith(("LICENSE", "COPYING")):
            name = parts[1]
        else:
            continue
        found.append((Path(str(distribution.locate_file(file))), name))
    return found


def notices(found: Bundled) -> str:
    """``THIRD-PARTY-NOTICES.txt``, with the versions the folder has."""
    return Template(NOTICES.read_text(encoding="utf-8")).substitute(
        kresorter=__version__,
        python=found.python,
        pyside6=found.version("PySide6_Essentials"),
        shiboken6=found.version("shiboken6"),
        qt=found.qt,
        pyinstaller=found.version("pyinstaller"),
    )


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def licences(folder: Path, found: Bundled) -> None:
    """Kresorter's licence and the notices beside ``Kresorter.exe``; the other texts in
    ``licenses``, those of a distribution in a folder of its name."""
    _copy(ROOT / "LICENSE", folder / "LICENSE")
    (folder / "THIRD-PARTY-NOTICES.txt").write_text(notices(found), encoding="utf-8")
    texts = folder / "licenses"
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        _copy(GNU / name, texts / name)
    _copy(found.python_licence, texts / "Python" / "LICENSE.txt")
    for distribution in found.distributions:
        for source, name in shipped(distribution):
            _copy(source, texts / distribution.metadata["Name"] / name)


# --- the portable zip ---------------------------------------------------------------------------


def portable_zip(folder: Path, out: Path, version: str = __version__) -> Path:
    """``Kresorter-<version>-portable.zip`` in ``out``: the folder and every file in it."""
    made = out / f"{NAME}-{version}-portable.zip"
    names = sorted(
        path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()
    )
    with zipfile.ZipFile(made, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
        for name in names:
            archive.write(folder / name, f"{folder.name}/{name}")
    return made


def finish(folder: Path, out: Path, found: Bundled) -> Path:
    """Once PyInstaller has made ``folder``: its licences, then its zip in ``out``."""
    licences(folder, found)
    return portable_zip(folder, out)
