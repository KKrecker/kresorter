"""The Windows application (decision 0015, items 12 to 15), as far as any system can check it.

Windows builds it, in CI (items 21 and 22). Here ``packaging/windows/kresorter.spec`` runs with
stand-ins for PyInstaller's targets, which record what they are given, and ``winbuild``, beside
the spec, runs as the spec runs it: the icon drawn from the sidebar's mark, the version
resource, the package's files and modules, the licences put in the folder and the portable zip.
``kresorter.iss`` is read as Inno Setup reads it: the keys of ``[Setup]``, the entries of every
other section, the preprocessor's lines.
"""

from __future__ import annotations

import importlib.metadata as metadata
import pkgutil
import platform
import re
import runpy
import struct
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
import winbuild
from PySide6 import QtCore
from PySide6.QtGui import QImage

import kresorter
from kresorter import __version__
from kresorter.environment import default_context
from kresorter.ui import launch
from kresorter.ui.theme import LIGHT
from support.markdown import section

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "packaging" / "windows"
SPEC = WINDOWS / "kresorter.spec"
ISS = WINDOWS / "kresorter.iss"
PACKAGE = Path(kresorter.__file__).resolve().parent
SRC = ROOT / "src" / "kresorter"


# --- made-up installed distributions -------------------------------------------------------------


def distribution(
    site: Path, name: str, version: str, files: dict[str, str]
) -> metadata.Distribution:
    """A distribution installed in ``site`` with ``files`` (paths from ``site``) in its RECORD."""
    info = site / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n", encoding="utf-8"
    )
    for relative, text in files.items():
        path = site / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    listed = [*files, f"{info.name}/METADATA", f"{info.name}/RECORD"]
    (info / "RECORD").write_text("".join(f"{line},,\n" for line in listed), encoding="utf-8")
    return metadata.PathDistribution(info)


def bundled(tmp_path: Path) -> winbuild.Bundled:
    """PySide6 and PyInstaller with their licence files as PEP 639 has them, shiboken6 with one
    at the top of its .dist-info, as older wheels had them."""
    site = tmp_path / "site"
    licence = tmp_path / "python" / "LICENSE.txt"
    licence.parent.mkdir()
    licence.write_text("Python's licence\n", encoding="utf-8")
    return winbuild.Bundled(
        distributions=(
            distribution(
                site,
                "PySide6_Essentials",
                "6.12.0",
                {
                    "PySide6_Essentials-6.12.0.dist-info/licenses/LicenseRef-Qt-Commercial.txt": (
                        "Qt's commercial terms\n"
                    ),
                    "PySide6/__init__.py": "",
                },
            ),
            distribution(
                site, "shiboken6", "6.12.0", {"shiboken6-6.12.0.dist-info/LICENSE.LGPLv3": "LGPL\n"}
            ),
            distribution(
                site,
                "pyinstaller",
                "6.22.3",
                {"pyinstaller-6.22.3.dist-info/licenses/COPYING.txt": "PyInstaller's licence\n"},
            ),
        ),
        python="3.13.9",
        qt="6.12.1",
        python_licence=licence,
    )


# --- the spec, with PyInstaller's targets recorded -----------------------------------------------


@dataclass
class Target:
    """What the spec gave one of PyInstaller's targets; an analysis' lists are named."""

    kind: str
    args: tuple[object, ...]
    options: dict[str, object]
    pure: str = "the analysis' modules"
    scripts: str = "the analysis' scripts"
    binaries: str = "the analysis' binaries"
    datas: str = "the analysis' data files"


@dataclass(frozen=True)
class Ran:
    made: list[Target]
    dist: Path
    work: Path

    def one(self, kind: str) -> Target:
        (found,) = [target for target in self.made if target.kind == kind]
        return found


def run_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ran:
    """The spec as PyInstaller runs it, its folder made as COLLECT would make it."""
    made: list[Target] = []
    dist, work = tmp_path / "dist", tmp_path / "build" / "kresorter"

    def target(kind: str) -> Callable[..., Target]:
        def make(*args: object, **options: object) -> Target:
            found = Target(kind, args, options)
            made.append(found)
            if kind == "COLLECT":
                folder = dist / str(options["name"])
                (folder / "_internal" / "PySide6").mkdir(parents=True)
                (folder / "Kresorter.exe").write_bytes(b"MZ")
                (folder / "_internal" / "PySide6" / "Qt6Core.dll").write_bytes(b"MZ")
            return found

        return make

    found = bundled(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))  # the spec puts its folder first
    monkeypatch.setattr(winbuild, "installed_package", lambda: PACKAGE)
    monkeypatch.setattr(winbuild, "bundled", lambda: found)
    namespace: dict[str, object] = {
        "SPEC": str(SPEC),
        "SPECPATH": str(WINDOWS),
        "specnm": "kresorter",
        "DISTPATH": str(dist),
        "workpath": str(work),
        **{kind: target(kind) for kind in ("Analysis", "PYZ", "EXE", "COLLECT")},
    }
    exec(compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec"), namespace)
    return Ran(made, dist, work)


def files(folder: Path) -> list[str]:
    return sorted(
        path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()
    )


# --- item 12: one folder, the window, the icon, the version resource ----------------------------


def test_the_spec_makes_one_folder_with_the_window_and_no_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0015.12] Kresorter.exe beside its files (exclude_binaries: not one file), no console
    ran = run_spec(tmp_path, monkeypatch)

    assert [target.kind for target in ran.made] == ["Analysis", "PYZ", "EXE", "COLLECT"]
    analysis, pyz, exe, collect = ran.made
    assert analysis.args == ([str(WINDOWS / "kresorter_window.py")],)
    assert pyz.args == (analysis.pure,)
    assert exe.args == (pyz, analysis.scripts, [])
    assert exe.options["name"] == "Kresorter"
    assert exe.options["console"] is False
    assert exe.options["exclude_binaries"] is True
    assert collect.args == (exe, analysis.binaries, analysis.datas)
    assert collect.options["name"] == "Kresorter"


def test_the_executable_runs_what_kresorter_ui_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    # [0015.12] the window, and the exit code it ends with
    called: list[str] = []

    def main() -> int:
        called.append("main")
        return 7

    monkeypatch.setattr(launch, "main", main)

    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(WINDOWS / "kresorter_window.py"), run_name="__main__")

    assert stopped.value.code == 7
    assert called == ["main"]


def test_the_package_is_searched_where_its_wheel_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0015.12] the wheel's folder first, so that no other copy of kresorter is taken
    analysis = run_spec(tmp_path, monkeypatch).one("Analysis")

    assert analysis.options["pathex"] == [str(PACKAGE.parent)]


def test_the_package_brings_its_files_and_every_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0015.12] its rules, its icons and their licence, as the wheel has them; every module,
    # since some are imported by name, which PyInstaller does not follow
    analysis = run_spec(tmp_path, monkeypatch).one("Analysis")

    datas = analysis.options["datas"]
    assert isinstance(datas, list)
    found = {
        (Path(source).relative_to(PACKAGE.parent).as_posix(), Path(folder).as_posix())
        for source, folder in datas
    }
    expected = {
        (
            path.relative_to(PACKAGE.parent).as_posix(),
            path.parent.relative_to(PACKAGE.parent).as_posix(),
        )
        for path in PACKAGE.rglob("*")
        if path.is_file() and path.suffix not in {".py", ".pyc"} and "__pycache__" not in path.parts
    }
    assert found == expected
    assert {
        ("kresorter/core/junk_rules.toml", "kresorter/core"),
        ("kresorter/ui/icons/shield-check.svg", "kresorter/ui/icons"),
        ("kresorter/ui/icons/LICENSE", "kresorter/ui/icons"),
        ("kresorter/py.typed", "kresorter"),
    } <= found
    hidden = analysis.options["hiddenimports"]
    assert isinstance(hidden, list)
    walked = {module.name for module in pkgutil.walk_packages(kresorter.__path__, "kresorter.")}
    assert {"kresorter", *walked} <= set(hidden)


def test_what_the_package_imports_by_name_travels_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0015.12] each name src gives importlib.import_module, but fcntl, which Windows has not;
    # and Qt's SVG module, which Qt loads for the icons
    hidden = run_spec(tmp_path, monkeypatch).one("Analysis").options["hiddenimports"]
    named = {
        name
        for path in SRC.rglob("*.py")
        for name in re.findall(r'import_module\("([\w.]+)"\)', path.read_text(encoding="utf-8"))
    }

    assert {"ctypes", "msvcrt", "winreg", "fcntl"} <= named
    assert isinstance(hidden, list)
    assert {*named - {"fcntl"}, "PySide6.QtSvg"} <= set(hidden)


def icon_images(path: Path) -> list[tuple[int, QImage]]:
    """Each image of an ICO file, with the side its entry gives: PNG, 32 bits."""
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind) == (0, 1)
    found: list[tuple[int, QImage]] = []
    for index in range(count):
        width, height, colours, _, planes, bits, size, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * index
        )
        blob = data[offset : offset + size]
        assert blob.startswith(b"\x89PNG\r\n\x1a\n")
        assert (height, colours, planes, bits) == (width, 0, 1, 32)
        found.append((width or 256, QImage.fromData(blob)))
    return found


def test_the_icon_is_the_sidebars_mark_at_each_size_windows_shows(tmp_path: Path) -> None:
    # [0015.12] the accent's tile, its corners rounded, the shield in the primary button's text
    images = icon_images(winbuild.icon(tmp_path / "build" / "kresorter.ico"))

    assert [side for side, _ in images] == [16, 20, 24, 32, 40, 48, 64, 256]
    for side, image in images:
        assert (image.width(), image.height()) == (side, side)
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(side // 2, 0).name() == LIGHT.accent.lower()
    large = images[-1][1]
    colours = {large.pixelColor(x, y).name() for x in range(0, 256, 2) for y in range(0, 256, 2)}
    assert LIGHT.primary_text.lower() in colours


def test_the_spec_gives_the_executable_the_icon_and_the_version_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0015.12] both made in PyInstaller's work folder, where the installer finds the icon too
    ran = run_spec(tmp_path, monkeypatch)

    exe = ran.one("EXE")
    assert exe.options["icon"] == str(ran.work / "kresorter.ico")
    assert [side for side, _ in icon_images(ran.work / "kresorter.ico")] == list(winbuild.SIDES)
    assert exe.options["version"] == str(ran.work / "version.txt")
    resource = (ran.work / "version.txt").read_text(encoding="utf-8")
    assert strings(resource)["ProductVersion"] == __version__


@dataclass(frozen=True)
class Made:
    """One of PyInstaller's version-resource classes, as the resource calls it."""

    name: str
    args: tuple[object, ...]
    options: dict[str, object]


RESOURCE_CLASSES = (
    "VSVersionInfo",
    "FixedFileInfo",
    "StringFileInfo",
    "StringTable",
    "StringStruct",
    "VarFileInfo",
    "VarStruct",
)


def resource(text: str) -> Made:
    """The version resource evaluated as PyInstaller evaluates it, its classes recorded."""

    def named(name: str) -> Callable[..., Made]:
        def make(*args: object, **options: object) -> Made:
            return Made(name, args, options)

        return make

    found = eval(text, {name: named(name) for name in RESOURCE_CLASSES})
    assert isinstance(found, Made)
    return found


def strings(text: str) -> dict[str, str]:
    """The resource's strings: each StringStruct's name and value."""
    found: dict[str, str] = {}

    def walk(item: object) -> None:
        if isinstance(item, Made):
            if item.name == "StringStruct":
                name, value = item.args
                found[str(name)] = str(value)
            for part in (*item.args, *item.options.values()):
                walk(part)
        elif isinstance(item, list):
            for part in item:
                walk(part)

    walk(resource(text))
    return found


def test_the_version_resource_names_kresorter_its_version_and_author(tmp_path: Path) -> None:
    # [0015.12] product Kresorter, the version of item 2, KKrecker, "Safe file cleanup"
    text = winbuild.version_file(tmp_path / "build" / "version.txt").read_text(encoding="utf-8")

    assert strings(text) == {
        "CompanyName": "KKrecker",
        "FileDescription": "Safe file cleanup",
        "FileVersion": __version__,
        "InternalName": "Kresorter",
        "LegalCopyright": "Copyright (c) 2026 KKrecker",
        "OriginalFilename": "Kresorter.exe",
        "ProductName": "Kresorter",
        "ProductVersion": __version__,
    }
    fixed = resource(text).options["ffi"]
    assert isinstance(fixed, Made)
    numbers = (*(int(part) for part in __version__.split(".")), 0)
    assert fixed.options["filevers"] == numbers
    assert fixed.options["prodvers"] == numbers


@pytest.mark.parametrize("version", ["0.1", "0.1.0rc1", "1.2.3.4"])
def test_a_version_windows_cannot_number_stops_the_build(version: str) -> None:
    # [0015.12] the resource has four numbers: those of X.Y.Z, then 0
    with pytest.raises(winbuild.BuildError, match=r"X\.Y\.Z"):
        winbuild.version_text(version)


def test_kresorter_is_taken_from_its_installed_wheel(tmp_path: Path) -> None:
    # [0015.12] the wheel's RECORD lists the package's modules
    site = tmp_path / "site"
    found = distribution(site, "kresorter", __version__, {"kresorter/__init__.py": ""})

    assert winbuild.wheel_package(found) == site / "kresorter"


def test_an_editable_install_is_refused(tmp_path: Path) -> None:
    # [0015.12] it lists a .pth file that points at the source tree, not the package
    found = distribution(tmp_path / "site", "kresorter", __version__, {"_kresorter.pth": "src\n"})

    with pytest.raises(winbuild.BuildError, match="wheel"):
        winbuild.wheel_package(found)


def test_kresorter_not_installed_is_refused() -> None:
    # [0015.12]
    with pytest.raises(winbuild.BuildError, match="wheel"):
        winbuild.installed_package("kresorter-never-installed")


# --- item 13: the licences ----------------------------------------------------------------------


def test_the_licences_travel_with_the_folder(tmp_path: Path) -> None:
    # [0015.13] Kresorter's, the notices, LGPLv3 with the GPLv3 it adds to, Python's, and the
    # licence files the wheels ship, each in a folder of its own
    folder = tmp_path / "Kresorter"
    folder.mkdir()
    found = bundled(tmp_path)

    winbuild.licences(folder, found)

    assert files(folder) == [
        "LICENSE",
        "THIRD-PARTY-NOTICES.txt",
        "licenses/GPL-3.0.txt",
        "licenses/LGPL-3.0.txt",
        "licenses/PySide6_Essentials/LicenseRef-Qt-Commercial.txt",
        "licenses/Python/LICENSE.txt",
        "licenses/pyinstaller/COPYING.txt",
        "licenses/shiboken6/LICENSE.LGPLv3",
    ]

    def text(relative: str) -> str:
        return (folder / relative).read_text(encoding="utf-8")

    assert text("LICENSE") == (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text("THIRD-PARTY-NOTICES.txt") == winbuild.notices(found)
    assert text("licenses/LGPL-3.0.txt").splitlines()[:2] == [
        "                   GNU LESSER GENERAL PUBLIC LICENSE",
        "                       Version 3, 29 June 2007",
    ]
    assert text("licenses/GPL-3.0.txt").splitlines()[:2] == [
        "                    GNU GENERAL PUBLIC LICENSE",
        "                       Version 3, 29 June 2007",
    ]
    assert text("licenses/Python/LICENSE.txt") == "Python's licence\n"
    assert text("licenses/PySide6_Essentials/LicenseRef-Qt-Commercial.txt") == (
        "Qt's commercial terms\n"
    )
    assert text("licenses/pyinstaller/COPYING.txt") == "PyInstaller's licence\n"


def test_the_notices_name_each_part_its_licence_and_where_its_source_is(tmp_path: Path) -> None:
    # [0015.13] with the versions the folder has
    text = winbuild.notices(bundled(tmp_path))

    assert "$" not in text
    flat = " ".join(text.split())
    for words in (
        f"Kresorter {__version__}",
        "MIT License",
        "Python 3.13.9",
        "https://www.python.org/downloads/source/",
        "PySide6 6.12.0 and shiboken6 6.12.0",
        "GNU Lesser General Public License version 3",
        r"licenses\LGPL-3.0.txt",
        r"licenses\GPL-3.0.txt",
        "https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.12.0",
        "Qt 6.12.1",
        r"_internal\PySide6",
        "replace",
        "https://download.qt.io/official_releases/qt/",
        "Lucide",
        "ISC License",
        r"_internal\kresorter\ui\icons\LICENSE",
        "PyInstaller 6.22.3",
        "bootloader",
        "exception",
        "https://github.com/pyinstaller/pyinstaller/tree/v6.22.3",
    ):
        assert words in flat, words


def test_what_the_folder_carries_is_looked_up_where_it_is_installed() -> None:
    # [0015.13] here PySide6 and shiboken6; the build adds PyInstaller, which runs it
    found = winbuild.bundled(("PySide6_Essentials", "shiboken6"))

    assert [d.metadata["Name"] for d in found.distributions] == ["PySide6_Essentials", "shiboken6"]
    assert found.python == platform.python_version()
    assert found.qt == QtCore.qVersion()
    assert found.python_licence.is_file()
    assert winbuild.BUNDLED == ("PySide6_Essentials", "shiboken6", "pyinstaller")


def test_a_distribution_not_installed_stops_the_build() -> None:
    # [0015.13]
    with pytest.raises(winbuild.BuildError, match="never-installed"):
        winbuild.bundled(("never-installed",))


def test_pythons_licence_is_where_its_installation_keeps_it(tmp_path: Path) -> None:
    # [0015.13] beside the standard library on Linux, at the top of the installation on Windows
    first, second = tmp_path / "lib" / "LICENSE.txt", tmp_path / "LICENSE.txt"
    second.write_text("PSF\n", encoding="utf-8")

    assert winbuild.python_licence((first, second)) == second
    with pytest.raises(winbuild.BuildError, match=r"LICENSE\.txt"):
        winbuild.python_licence((first,))


def test_qts_libraries_stay_files_of_their_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0015.13] one folder, nothing compressed into another file: a user can replace them
    ran = run_spec(tmp_path, monkeypatch)

    assert ran.one("EXE").options["exclude_binaries"] is True
    assert ran.one("EXE").options["upx"] is False
    assert ran.one("COLLECT").options["upx"] is False
    assert "_internal/PySide6/Qt6Core.dll" in files(ran.dist / "Kresorter")


# --- item 14: the portable zip -------------------------------------------------------------------


def test_the_portable_zip_is_the_folder(tmp_path: Path) -> None:
    # [0015.14] Kresorter-<version>-portable.zip: the folder Kresorter and every file in it
    folder = tmp_path / "dist" / "Kresorter"
    (folder / "_internal" / "PySide6").mkdir(parents=True)
    (folder / "Kresorter.exe").write_bytes(b"MZ")
    (folder / "_internal" / "PySide6" / "Qt6Core.dll").write_bytes(b"Qt")

    made = winbuild.portable_zip(folder, tmp_path / "dist", "0.1.0")

    assert made == tmp_path / "dist" / "Kresorter-0.1.0-portable.zip"
    with zipfile.ZipFile(made) as archive:
        assert archive.namelist() == [
            "Kresorter/Kresorter.exe",
            "Kresorter/_internal/PySide6/Qt6Core.dll",
        ]
        assert archive.read("Kresorter/_internal/PySide6/Qt6Core.dll") == b"Qt"


def test_the_spec_puts_the_licences_in_the_folder_then_zips_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0015.13] [0015.14] once PyInstaller has made the folder, beside which the zip is
    ran = run_spec(tmp_path, monkeypatch)

    folder = ran.dist / "Kresorter"
    assert {"LICENSE", "THIRD-PARTY-NOTICES.txt", "licenses/LGPL-3.0.txt"} <= set(files(folder))
    with zipfile.ZipFile(ran.dist / f"Kresorter-{__version__}-portable.zip") as archive:
        assert archive.namelist() == [f"Kresorter/{name}" for name in files(folder)]


def test_the_portable_one_keeps_its_data_where_the_installed_one_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0015.14] wherever Kresorter.exe runs from, its data directory is the system's
    # (%LOCALAPPDATA%\kresorter on Windows), never beside it
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    found: set[Path] = set()
    for folder in (tmp_path / "Programs" / "Kresorter", tmp_path / "usb" / "Kresorter"):
        monkeypatch.setattr(sys, "executable", str(folder / "Kresorter.exe"))
        data = Path(default_context().policy.app_data_dir)
        assert folder not in (data, *data.parents)
        found.add(data)

    assert len(found) == 1


# --- item 15: the installer ----------------------------------------------------------------------


@dataclass(frozen=True)
class Script:
    """An Inno Setup script: the keys of [Setup], the entries of every other section, each a
    parameter's value by its name, and the preprocessor's lines."""

    setup: dict[str, str]
    sections: dict[str, list[dict[str, str]]]
    preprocessor: list[str]
    code: str  # without comments


PARAMETER = re.compile(r'(\w+):\s*("[^"]*"|[^;]*)')


def script() -> Script:
    setup: dict[str, str] = {}
    sections: dict[str, list[dict[str, str]]] = {}
    preprocessor: list[str] = []
    code: list[str] = []
    current = ""
    for line in (stripped.strip() for stripped in ISS.read_text(encoding="utf-8").splitlines()):
        if not line or line.startswith(";"):
            continue
        code.append(line)
        if line.startswith("#"):
            preprocessor.append(line)
        elif line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections[current] = []
        elif current == "Setup":
            key, value = line.split("=", 1)
            setup[key.strip()] = value.strip()
        else:
            sections[current].append(
                {name: value.strip().strip('"') for name, value in PARAMETER.findall(line)}
            )
    return Script(setup, sections, preprocessor, "\n".join(code))


def test_the_installer_is_for_the_current_user_without_administrator_rights() -> None:
    # [0015.15] into %LOCALAPPDATA%\Programs\Kresorter, which Inno Setup names {userpf}
    setup = script().setup

    assert setup["PrivilegesRequired"] == "lowest"
    assert "PrivilegesRequiredOverridesAllowed" not in setup
    assert setup["DefaultDirName"] == r"{userpf}\Kresorter"


def test_the_installer_is_named_by_the_version_it_is_given() -> None:
    # [0015.15] Kresorter-0.1.0-setup.exe: the build gives __version__, which nothing replaces
    found = script()

    assert found.setup["OutputBaseFilename"] == "Kresorter-{#AppVersion}-setup"
    assert found.preprocessor[:2] == ["#ifndef AppVersion", found.preprocessor[1]]
    assert found.preprocessor[1].startswith("#error ")
    assert not any(line.startswith("#define AppVersion") for line in found.preprocessor)


def test_the_installer_installs_the_folder_the_spec_makes_with_its_icon() -> None:
    # [0015.15] dist\Kresorter and the icon in PyInstaller's work folder, from the repository
    found = script()

    [entry] = found.sections["Files"]
    assert entry["Source"] == r"{#Folder}\*"
    assert entry["DestDir"] == "{app}"
    assert {"recursesubdirs", "createallsubdirs"} <= set(entry["Flags"].split())
    assert r'#define Folder Root + "dist\Kresorter"' in found.preprocessor
    assert r'#define Icon Root + "build\kresorter\kresorter.ico"' in found.preprocessor
    assert found.setup["SetupIconFile"] == "{#Icon}"


def test_the_installer_makes_a_start_menu_shortcut_and_a_desktop_one_if_asked() -> None:
    # [0015.15] the desktop one is a task, unchecked; a silent install starts nothing
    found = script()

    assert found.sections["Icons"] == [
        {"Name": r"{userprograms}\Kresorter", "Filename": r"{app}\Kresorter.exe"},
        {
            "Name": r"{userdesktop}\Kresorter",
            "Filename": r"{app}\Kresorter.exe",
            "Tasks": "desktopicon",
        },
    ]
    [task] = found.sections["Tasks"]
    assert task["Name"] == "desktopicon"
    assert task["Flags"].split() == ["unchecked"]
    [run] = found.sections["Run"]
    assert run["Filename"] == r"{app}\Kresorter.exe"
    assert "skipifsilent" in run["Flags"].split()


def test_the_installer_is_listed_in_apps_with_its_version_and_author() -> None:
    # [0015.15] a fixed AppId: a new version replaces the old one in the list
    setup = script().setup

    assert setup["AppName"] == "Kresorter"
    assert setup["AppVersion"] == "{#AppVersion}"
    assert setup["AppPublisher"] == "KKrecker"
    assert setup["UninstallDisplayName"] == "Kresorter"
    assert setup["UninstallDisplayIcon"] == r"{app}\Kresorter.exe"
    assert re.fullmatch(r"\{\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}", setup["AppId"])


def test_the_installer_speaks_the_windows_languages() -> None:
    # [0015.15] English and Russian
    names = [entry["Name"] for entry in script().sections["Languages"]]

    assert names == ["english", "russian"]


def test_the_uninstaller_removes_what_was_installed_and_never_the_data_directory() -> None:
    # [0015.15] no [UninstallDelete], no [UninstallRun], no [Code], no [Registry], and no path
    # of the data directory, which is in %LOCALAPPDATA%
    found = script()

    assert set(found.sections) == {"Setup", "Languages", "Tasks", "Files", "Icons", "Run"}
    code = found.code.lower()
    for words in ("{localappdata}", "{userappdata}", "%localappdata%", "uninsdelete"):
        assert words not in code


def test_the_readme_says_how_to_uninstall_and_that_the_data_stay() -> None:
    # [0015.15] the quarantined files are still there: restore or purge them first; removing
    # the data directory is the user's own step
    text = " ".join(section((ROOT / "README.md").read_text(encoding="utf-8"), "Uninstalling"))
    flat = " ".join(text.split())

    for words in (
        "`kresorter quarantine list`",
        "Quarantine page",
        "restore",
        "purge",
        r"`%LOCALAPPDATA%\kresorter`",
        r"`%LOCALAPPDATA%\Programs\Kresorter`",
        "your own step",
        "pipx uninstall kresorter",
    ):
        assert words in flat, words
    assert re.search(r"\b(rm|rmdir|del|rd|Remove-Item)\b", flat) is None  # no command for it
