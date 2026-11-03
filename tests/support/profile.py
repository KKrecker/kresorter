"""A made-up Windows profile for the live tests of Windows (decision 0016, item 9; 0017, item
13): the running system's context, made for a home under ``tmp_path``.

One rule leaves its classifier: the runner's temporary folder is ``AppData\\Local\\Temp``,
which ``windows-user-temp`` marks as junk, as the tests of Linux leave ``posix-temp`` out. The
home is taken resolved: a short name (``RUNNER~1``) leads elsewhere (0017, item 12).
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from kresorter import environment
from kresorter.core.heuristics import JunkClassifier, default_rules
from kresorter.core.scanner import ScanContext


def windows_context(home: Path, **variables: str) -> ScanContext:
    """``default_context`` for the profile at ``home``: the names the policy reads, and
    ``variables`` beside them (``os.environ`` ignores the case on Windows)."""
    profile = {
        "SystemDrive": os.environ.get("SYSTEMDRIVE", "C:"),
        "SystemRoot": os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        **variables,
    }
    made = environment.default_context(env=profile)
    rules = [r for r in default_rules() if r.id != "windows-user-temp"]
    return replace(made, classifier=JunkClassifier(rules, platform="windows"))
