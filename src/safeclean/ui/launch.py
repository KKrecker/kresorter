"""``safeclean-ui`` and ``python -m safeclean.ui`` (decision 0014, items 8 and 9).

Without PySide6 the window cannot open: one line on stderr names the extra that installs it,
nothing is created, and the exit code is 3. Any other import error of the window is raised.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence

from safeclean.environment import Environment

__all__ = ["main"]

NO_QT = 'safeclean-ui: the desktop window needs PySide6 (pip install "safeclean[ui]"): {}\n'
_QT_ROOTS = ("PySide6", "shiboken6")
NO_WINDOW = 3


def main(argv: Sequence[str] | None = None, *, environment: Environment | None = None) -> int:
    """Open the window; its exit code once it is closed (0), or 3 without PySide6."""
    try:
        app = importlib.import_module("safeclean.ui.app")
    except ImportError as error:
        if (error.name or "").split(".")[0] not in _QT_ROOTS:
            raise
        sys.stderr.write(NO_QT.format(error))
        return NO_WINDOW
    run = app.run
    return int(run(sys.argv[:1] if argv is None else argv, environment or Environment()))
