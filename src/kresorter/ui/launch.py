"""``kresorter-ui`` and ``python -m kresorter.ui`` (decision 0014, items 8 and 9).

Without Qt the window cannot open: one line on stderr says why, PySide6 missing (and the extra
that installs it) or a library Qt cannot load (and those Qt needs on Linux); nothing is
created, and the exit code is 3. Without a standard error, as for a GUI script on Windows and
``Kresorter.exe``, the line is shown in the system's message box there (``MessageBoxW``
through ``ctypes``, which needs no Qt) and nowhere elsewhere (decision 0015, item 24). An
import error of the window's own modules is raised. The one option, ``--self-test REPORT``, is
read before Qt is imported (item 17).
"""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from kresorter.environment import Environment

__all__ = ["Options", "main", "options"]

NO_QT = 'kresorter-ui: the desktop window needs PySide6 (pip install "kresorter[ui]"): {}\n'
NO_LIBRARY = (
    "kresorter-ui: Qt cannot load a library it needs ({}); on Linux, install libegl1, libgl1,"
    " libxkbcommon0, libfontconfig1 and libdbus-1-3\n"
)
_QT_ROOTS = ("PySide6", "shiboken6")
NO_WINDOW = 3
MB_ICONERROR = 0x10  # with MB_OK (0): one button
TITLE = "Kresorter"


class _User32(Protocol):
    def MessageBoxW(self, window: None, text: str, caption: str, kind: int, /) -> int: ...


class _Ctypes(Protocol):
    def WinDLL(self, name: str) -> _User32: ...


@dataclass(frozen=True)
class Options:
    self_test: Path | None = None  # the report of the self-test, which runs instead


def options(argv: Sequence[str]) -> Options:
    """The options of ``argv`` (without the program's name); usage errors exit with 2."""
    parser = argparse.ArgumentParser(prog="kresorter-ui", description="Kresorter's desktop window.")
    parser.add_argument(
        "--self-test",
        metavar="REPORT",
        type=Path,
        help="open the window, show each page and close it, changing nothing; write one line"
        " per page to REPORT and exit with 0, or the traceback of a failure and exit with 1",
    )
    return Options(parser.parse_args(list(argv)).self_test)


def main(argv: Sequence[str] | None = None, *, environment: Environment | None = None) -> int:
    """Open the window; its exit code once it is closed (0), or 3 without Qt. ``argv``: the
    arguments after the program's name."""
    chosen = options(sys.argv[1:] if argv is None else argv)
    try:
        importlib.import_module("PySide6.QtWidgets")
    except ImportError as error:  # a binding that cannot load a library names itself alone
        missing = (error.name or "").split(".")[0] in _QT_ROOTS
        _say((NO_QT if missing else NO_LIBRARY).format(error))
        return NO_WINDOW
    run = importlib.import_module("kresorter.ui.app").run
    return int(run(sys.argv[:1], environment or Environment(), chosen.self_test))


def _say(line: str) -> None:
    if sys.stderr is not None:  # a GUI script on Windows has none
        sys.stderr.write(line)
    elif _on_windows():
        message_box(line.rstrip("\n"))


def _on_windows() -> bool:
    return sys.platform == "win32"


def message_box(text: str, module: _Ctypes | None = None) -> None:
    """``text`` in the system's message box, with an error icon and OK; Windows only."""
    found = module or cast("_Ctypes", importlib.import_module("ctypes"))
    found.WinDLL("user32").MessageBoxW(None, text, TITLE, MB_ICONERROR)
