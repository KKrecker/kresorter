"""Fixtures shared by several test files (decision 0011, item 123).

pytest finds a fixture by its name, so these are not imported; helpers are imported by name
from ``support``, and boundary fakes from ``fakes``.
"""

from pathlib import Path

import pytest

from safeclean.core.scanner import ScanContext
from support.cli import scan_context


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """safeclean's data directory, not made: commands make it, after checking where it is."""
    return tmp_path / "data" / "safeclean"


@pytest.fixture
def zone(tmp_path: Path) -> Path:
    """The one default scan zone, made empty."""
    path = tmp_path / "zone"
    path.mkdir()
    return path


@pytest.fixture
def scan(tmp_path: Path, zone: Path, data_dir: Path) -> ScanContext:
    """The scan context of a CLI test: ``zone`` and ``data_dir``, a reliable open-file check."""
    return scan_context(tmp_path, zone, data_dir)
