"""``safeclean-ui`` and ``python -m safeclean.ui`` (decision 0014, items 8 and 9).

Without Qt the window cannot open: one line on stderr says why, PySide6 missing (and the extra
that installs it) or a library Qt cannot load (and those Qt needs on Linux); nothing is
created, and the exit code is 3. Without a standard error, as for a GUI script on Windows, the
line is not written. An import error of the window's own modules is raised.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence

from safeclean.environment import Environment

__all__ = ["main"]

NO_QT = 'safeclean-ui: the desktop window needs PySide6 (pip install "safeclean[ui]"): {}\n'
NO_LIBRARY = (
    "safeclean-ui: Qt cannot load a library it needs ({}); on Linux, install libegl1, libgl1,"
    " libxkbcommon0, libfontconfig1 and libdbus-1-3\n"
)
_QT_ROOTS = ("PySide6", "shiboken6")
NO_WINDOW = 3


def main(argv: Sequence[str] | None = None, *, environment: Environment | None = None) -> int:
    """Open the window; its exit code once it is closed (0), or 3 without Qt."""
    try:
        importlib.import_module("PySide6.QtWidgets")
    except ImportError as error:  # a binding that cannot load a library names itself alone
        missing = (error.name or "").split(".")[0] in _QT_ROOTS
        _say((NO_QT if missing else NO_LIBRARY).format(error))
        return NO_WINDOW
    run = importlib.import_module("safeclean.ui.app").run
    return int(run(sys.argv[:1] if argv is None else argv, environment or Environment()))


def _say(line: str) -> None:
    if sys.stderr is not None:  # a GUI script on Windows has none
        sys.stderr.write(line)
