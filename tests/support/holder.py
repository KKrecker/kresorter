"""A file held open by another process, for the live tests of Windows (decision 0016, items 7
and 9): the child opens it, says so, and closes it when the block ends."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

HOLDER = """
import sys
with open(sys.argv[1], "rb"):
    print("holding", flush=True)
    sys.stdin.readline()
"""
LIMIT = 60.0  # seconds a child may take to close the file and exit


@contextmanager
def held_by_a_child(path: Path) -> Iterator[None]:
    """``path`` open for reading in a child process until the block ends."""
    child = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "holding"
        yield
    finally:
        child.communicate("\n", timeout=LIMIT)
