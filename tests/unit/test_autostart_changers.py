"""What changes autostart entries on each platform, for the CLI and the window (0014, 12)."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from fakes import FakeRegistry
from kresorter.autostart.changers import changes_for
from kresorter.autostart.changes import XdgChanges
from kresorter.autostart.registry import UserRegistry
from kresorter.autostart.run_changes import RunKeyChanges
from kresorter.storage.db import connect
from support.cli import autostart_context


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    yield connection
    connection.close()


def test_linux_changes_xdg_entries(conn: sqlite3.Connection, tmp_path: Path) -> None:
    # [0014.12]
    changes = changes_for(autostart_context("linux", tmp_path), conn, tmp_path / "data")
    assert isinstance(changes, XdgChanges)


def test_windows_changes_run_values_through_the_registry_it_opens(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    # [0014.12]
    opened: list[UserRegistry] = []
    registry = FakeRegistry({})
    context = autostart_context("windows", tmp_path, registry)
    original = context.registry

    def counted() -> UserRegistry:
        opened.append(original())
        return opened[-1]

    context = type(context)(
        context.platform, context.env, home=context.home, root=context.root, registry=counted
    )
    changes = changes_for(context, conn, tmp_path / "data")

    assert isinstance(changes, RunKeyChanges)
    assert opened == [registry]


def test_macos_changes_nothing(conn: sqlite3.Connection, tmp_path: Path) -> None:
    # [0014.12]
    assert changes_for(autostart_context("darwin", tmp_path), conn, tmp_path / "data") is None


def test_linux_opens_no_registry(conn: sqlite3.Connection, tmp_path: Path) -> None:
    # [0014.12]
    def no_registry() -> UserRegistry:
        raise AssertionError("no registry on Linux")

    context = autostart_context("linux", tmp_path)
    context = type(context)(
        context.platform, context.env, home=context.home, root=context.root, registry=no_registry
    )
    assert isinstance(changes_for(context, conn, tmp_path / "data"), XdgChanges)
