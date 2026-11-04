"""Qt's offscreen platform, on which the window's tests and the screenshots run (decision 0014,
item 38). It draws with the fonts of its font folder, which Qt's wheel for Windows leaves empty:
there every letter would be a box, all of one width, and a window as wide as its longest text in
boxes. On Windows its folder is the system's own (``QT_QPA_FONTDIR``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def system_fonts() -> None:
    """On Windows, the offscreen platform's fonts are the system's, unless a folder is set."""
    if sys.platform == "win32":
        windows = os.environ.get("SYSTEMROOT", r"C:\Windows")
        os.environ.setdefault("QT_QPA_FONTDIR", str(Path(windows, "Fonts")))
