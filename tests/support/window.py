"""What the window's tests share: an environment made for tmp_path, and the buttons that have
neither a text nor an accessible name (decision 0014, items 18 and 39)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QAbstractButton, QWidget

from safeclean.core.heuristics import Platform
from safeclean.environment import Environment
from support.cli import autostart_context, scan_context


def environment(
    tmp_path: Path, zone: Path, data_dir: Path, *, platform: Platform = "linux"
) -> Environment:
    """The window's environment for tmp_path: ``zone`` the one scan zone, ``data_dir`` the data
    directory, autostart under tmp_path, no setting of the local AI."""
    return Environment(
        scan_context=lambda: scan_context(tmp_path, zone, data_dir, platform=platform),
        autostart_context=lambda: autostart_context(platform, tmp_path),
        llm_env={},
    )


def unnamed(widget: QWidget) -> list[QAbstractButton]:
    """The buttons under ``widget`` with neither a text nor an accessible name."""
    return [
        button
        for button in widget.findChildren(QAbstractButton)
        if not (button.text().strip() or button.accessibleName().strip())
    ]
