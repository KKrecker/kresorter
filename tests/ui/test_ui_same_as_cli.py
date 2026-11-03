"""The window and the CLI on the same trees: the window's findings and levels are those of
``analyze --json``, its organize plan is that of ``organize move`` without ``--yes``, and its
autostart entries are those of ``autostart list --json`` (decision 0014, item 6)."""

import json
import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QTreeWidget
from pytestqt.qtbot import QtBot

from fakes import FakeRegistry
from kresorter.analysis.score import Level
from kresorter.autostart.models import Scope, Source
from kresorter.autostart.registry import Hive, RegValue, ValueKind
from kresorter.autostart.run_keys import RUN
from kresorter.organize.planner import StayReason
from kresorter.ui.i18n import Translator
from kresorter.ui.window import Window
from support.cli import autostart_context, run, scan_context
from support.files import write
from support.interrupted import APP
from support.moves import A, B, C, files, three_files
from support.window import (
    FakeDialogs,
    children,
    environment,
    junk_tree,
    make_window,
    scanned,
    settled,
    wait_idle,
)

EN = Translator("en")
_MOVE = re.compile(r"^    (?P<name>.+) -> (?P<category>[^/]+)/$")
_STAY = re.compile(r"^  (?P<reason>[a-z_]+): (?P<path>.+?)(?: \((?P<detail>.*)\))?$")


def _groups(tree: QTreeWidget) -> list[tuple[str, list[list[str]]]]:
    """Each group's title, with the cells of its rows."""
    root = tree.invisibleRootItem()
    groups = children(root)
    return [
        (
            group.text(0),
            [[row.text(c) for c in range(tree.columnCount())] for row in children(group)],
        )
        for group in groups
    ]


def test_the_findings_and_their_levels_are_those_of_analyze_json(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.6] The same findings, in the same order, with the same level, reasons and proposal.
    junk_tree(zone)
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    scanned(qtbot, window)

    _, out, _ = run(["analyze", "--json"], scan_context(tmp_path, zone, data_dir))

    expected = [
        (
            Path(found["path"]),
            found["level"],
            [(reason["evidence"], reason["detail"]) for reason in found["reasons"]],
            found["proposed"],
            found["kept_copy"],
        )
        for found in json.loads(out)["findings"]
    ]
    assert expected
    assert [
        (
            finding.entry.path,
            str(finding.level),
            [(str(reason.evidence), reason.detail) for reason in finding.reasons],
            finding.proposed,
            finding.keeps is not None,
        )
        for finding in window.findings.findings()
    ] == expected
    for path, level, *_ in expected:
        group = window.findings.item(path).parent()
        assert group is not None
        assert group.text(2) == EN.label(Level(level))


def test_the_organize_plan_is_that_of_organize_move_without_yes(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.6] The same moves by category, and the same files that stay, with their reasons.
    folder = three_files(zone)
    write(folder / "old" / "inside.jpg", b"inside")
    write(folder / ".hidden", b"hidden")
    write(folder / "old.tmp", b"old")
    dialogs = FakeDialogs(confirm=False, folders=[folder])
    window = make_window(qtbot, environment(tmp_path, zone, data_dir), dialogs=dialogs)
    window.show_page("organize")
    wait_idle(qtbot, window)
    page = window.organize
    page.choose_button.click()
    wait_idle(qtbot, window)
    page.move_button.click()  # its confirmation names every move; cancelled
    wait_idle(qtbot, window)

    code, out, _ = run(["organize", "move", str(folder)], scan_context(tmp_path, zone, data_dir))

    assert code == 1
    lines = out.splitlines()
    moves = [(m["name"], m["category"]) for m in map(_MOVE.match, lines) if m]
    stay_at = lines.index("Stays 3:")
    stays = [
        (m["path"], EN.reason(StayReason(m["reason"]), m["detail"] or ""))
        for m in map(_STAY.match, lines[stay_at + 1 : stay_at + 4])
        if m
    ]
    assert len(moves) == 3
    assert len(stays) == 3
    [asked] = dialogs.asked
    assert asked.details == tuple(f"{name} → {category}/" for name, category in moves)
    by_category: dict[str, list[str]] = {}
    for name, category in moves:
        by_category.setdefault(category, []).append(name)
    assert [(card.category, card.names.text()) for card in page.cards] == [
        (category, ", ".join(names)) for category, names in by_category.items()
    ]
    shown_stays = children(page.stays.invisibleRootItem())
    assert [(row.text(0), row.text(1)) for row in shown_stays] == stays
    assert page.stays.topLevelItemCount() == len(stays)
    assert not (folder / "Images").exists()


def test_what_the_russian_window_sorted_organize_undo_moves_back(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.44] The directories the window makes in Russian are those the CLI makes and knows.
    folder = three_files(zone)
    window = make_window(
        qtbot,
        environment(tmp_path, zone, data_dir),
        language="ru",
        dialogs=FakeDialogs(folders=[folder]),
    )
    window.show_page("organize")
    wait_idle(qtbot, window)
    window.organize.choose_button.click()
    wait_idle(qtbot, window)
    window.organize.move_button.click()
    wait_idle(qtbot, window)
    sorted_files = files(folder)

    code, out, _ = run(["organize", "undo", "1", "--yes"], scan_context(tmp_path, zone, data_dir))

    assert sorted_files == {
        f"Images/{A}": b"a.jpg",
        f"Documents/{B}": b"b.pdf",
        f"Audio/{C}": b"c.mp3",
    }
    assert code == 0
    assert "Images/a.jpg -> a.jpg" in out
    assert files(folder) == {A: b"a.jpg", B: b"b.pdf", C: b"c.mp3"}


Entry = tuple[str, bool, str, str]


def _entries(window: Window) -> list[tuple[str, list[Entry]]]:
    """Each section of the Autostart page, with each entry's name, its switch (on when it
    starts), its scope and its location (the name's tooltip)."""
    page = window.autostart
    return [
        (
            title,
            [
                (row[0], page.switch(row[0]).isChecked(), row[1], page.row(row[0]).toolTip(0))
                for row in rows
            ],
        )
        for title, rows in _groups(page.entries)
    ]


def _expected(items: list[dict[str, object]]) -> list[tuple[str, list[Entry]]]:
    """``autostart list --json``'s items as the Autostart page groups and shows them."""
    groups: dict[str, list[Entry]] = {}
    for item in items:
        source = EN.label(Source(str(item["source"])))
        cells = (
            str(item["name"]),
            bool(item["enabled"]),
            EN.label(Scope(str(item["scope"]))),
            str(item["location"]),
        )
        groups.setdefault(source, []).append(cells)
    return [(f"{source} · {EN.count('entry', len(rows))}", rows) for source, rows in groups.items()]


def test_the_autostart_entries_are_those_of_autostart_list_json(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.6] A user entry that replaces a system one, a disabled system entry, another.
    user = tmp_path / "config" / "autostart"
    system = tmp_path / "etc" / "xdg" / "autostart"
    write(system / "app.desktop", APP)
    write(user / "app.desktop", APP)
    write(system / "tray.desktop", APP.replace(b"Name=App", b"Name=Tray") + b"Hidden=true\n")
    write(user / "other.desktop", APP.replace(b"Name=App", b"Name=Other"))
    window = make_window(qtbot, environment(tmp_path, zone, data_dir))
    window.show_page("autostart")
    wait_idle(qtbot, window)

    _, out, _ = run(
        ["autostart", "list", "--json"],
        scan_context(tmp_path, zone, data_dir),
        autostart_context("linux", tmp_path),
    )

    items = json.loads(out)["items"]
    assert len(items) == 3
    assert _entries(window) == _expected(items)


@pytest.mark.parametrize("include_machine", [False, True])
def test_on_windows_the_entries_are_those_of_the_same_scope(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, include_machine: bool
) -> None:
    # [0014.6] [0014.37] The setting on: those of --include-machine; off: those without it.
    registry = FakeRegistry(
        {
            (Hive.HKCU, RUN): [RegValue("Sync", ValueKind.REG_SZ, r"C:\sync.exe")],
            (Hive.HKLM, RUN): [RegValue("Agent", ValueKind.REG_SZ, r"C:\agent.exe")],
        }
    )
    settled(data_dir, include_machine=include_machine)
    env = environment(tmp_path, zone, data_dir, platform="windows", registry=registry)
    window = make_window(qtbot, env)
    window.show_page("autostart")
    wait_idle(qtbot, window)

    flag = ["--include-machine"] if include_machine else []
    _, out, _ = run(
        ["autostart", "list", "--json", *flag],
        scan_context(tmp_path, zone, data_dir, platform="windows"),
        autostart_context("windows", tmp_path, registry),
    )

    items = json.loads(out)["items"]
    assert len(items) == 1 + include_machine
    assert _entries(window) == _expected(items)
