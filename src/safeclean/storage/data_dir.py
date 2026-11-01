"""The data directory: journal, lock, quarantine vault, autostart store (decisions 0004, 0009).

It must never be something a scan would offer: neither inside a default scan zone nor matched
by a junk rule. Callers check it before anything is created there; it and every directory
safeclean makes in it are private (pre-step-5 audit, B1).
"""

from __future__ import annotations

from pathlib import Path

from safeclean.core.heuristics import JunkClassifier
from safeclean.core.policy import PathPolicy

PRIVATE = 0o700


class DataDirError(Exception):
    """The data directory is somewhere a scan would offer it."""


def check_data_dir(policy: PathPolicy, classifier: JunkClassifier) -> Path:
    """The data directory, if no scan would offer it (decision 0009)."""
    data_dir = Path(policy.app_data_dir)
    for root in policy.default_roots():
        if data_dir.is_relative_to(root):
            raise DataDirError(f"data directory {data_dir} is inside scan zone {root}")
    match = classifier.classify(data_dir / "quarantine" / "0" / "0")  # its deepest: a vault slot
    if match is not None:
        raise DataDirError(f"data directory {data_dir} matches junk rule {match.rule_id}")
    return data_dir
