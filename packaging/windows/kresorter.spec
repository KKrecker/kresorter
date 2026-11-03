# Kresorter.exe and its folder (decision 0015, items 12 to 14), made on Windows by PyInstaller
# with the Python 3.13 of CI, in a virtual environment that has Kresorter's wheel with the
# extra ui and the tools of requirements.txt; from the repository's root:
#
#     pip install "dist/kresorter-0.1.0-py3-none-any.whl[ui]" -r packaging/windows/requirements.txt
#     pyinstaller --noconfirm packaging/windows/kresorter.spec
#
# dist/Kresorter is one folder: Kresorter.exe (the window, with no console, the sidebar's mark as
# its icon and a version resource), Python, Qt's libraries as files of their own, the package
# and the licences; dist/Kresorter-0.1.0-portable.zip is that folder. The icon is left in
# build/kresorter for the installer (kresorter.iss). What the spec computes is in winbuild.py,
# beside it, where the tests run it.
import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)

import winbuild

work, dist = Path(workpath), Path(DISTPATH)
package = winbuild.installed_package()
found = winbuild.bundled()

analysis = Analysis(
    [str(winbuild.SCRIPT)],
    pathex=[str(package.parent)],
    datas=winbuild.datas(package),
    hiddenimports=winbuild.hidden_imports(package),
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=winbuild.NAME,
    console=False,
    icon=str(winbuild.icon(work / "kresorter.ico")),
    version=str(winbuild.version_file(work / "version.txt")),
    upx=False,
)
COLLECT(exe, analysis.binaries, analysis.datas, upx=False, name=winbuild.NAME)
winbuild.finish(dist / winbuild.NAME, dist, found)
