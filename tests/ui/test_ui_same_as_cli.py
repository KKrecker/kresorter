"""The window and the CLI on the same trees: the window's findings and levels are those of
``analyze --json``, its organize plan is that of ``organize move`` without ``--yes``, and its
autostart entries are those of ``autostart list --json`` (decision 0014, item 6)."""

import json
import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
from pytestqt.qtbot import QtBot

from fakes import FakeRegistry
from safeclean.analysis.score import Level
from safeclean.autostart.models import Scope, Source
from safeclean.autostart.registry import Hive, RegValue, ValueKind
from safeclean.autostart.run_keys import RUN
from safeclean.organize.planner import StayReason
from safeclean.ui.i18n import Translator
from support.cli import autostart_context, run, scan_context
from support.files import write
from support.interrupted import APP
from support.moves import three_files
from support.window import (
    FakeDialogs,
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


def _child(item: QTreeWidgetItem, index: int) -> QTreeWidgetItem:
    child = item.child(index)
    assert child is not None
    return child


def _groups(tree: QTreeWidget) -> list[tuple[str, list[list[str]]]]:
    """Each group's title, with the cells of its rows."""
    root = tree.invisibleRootItem()
    groups = [_child(root, index) for index in range(root.childCount())]
    return [
        (
            group.text(0),
            [
                [_child(group, i).text(c) for c in range(tree.columnCount())]
                for i in range(group.childCount())
            ],
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
        assert window.findings.item(path).text(1) == EN.label(Level(level))


def test_the_organize_plan_is_that_of_organize_move_without_yes(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.6] The same moves by category, and the same files that stay, with their reasons.
    folder = three_files(zone)
    write(folder / "old" / "inside.jpg", b"inside")
    write(folder / ".hidden", b"hidden")
    write(folder / "old.tmp", b"old")
    window = make_window(
        qtbot, environment(tmp_path, zone, data_dir), dialogs=FakeDialogs(folders=[folder])
    )
    window.show_page("organize")
    wait_idle(qtbot, window)
    window.organize.choose_button.click()
    wait_idle(qtbot, window)

    code, out, _ = run(["organize", "move", str(folder)], scan_context(tmp_path, zone, data_dir))

    assert code == 1
    lines = out.splitlines()
    moves = [(m["name"], m["category"]) for m in map(_MOVE.match, lines) if m]
    stay_at = lines.index("Stays 3:")
    stays = [
        f"{m['path']} ({EN.reason(StayReason(m['reason']), m['detail'] or '')})"
        for m in map(_STAY.match, lines[stay_at + 1 : stay_at + 4])
        if m
    ]
    assert len(moves) == 3
    assert len(stays) == 3
    *categories, (stays_title, shown_stays) = _groups(window.organize.plan)
    shown_moves = [
        (match["name"], match["category"])
        for _, rows in categories
        for [row] in rows
        if (match := re.fullmatch(r"(?P<name>.+) → (?P<category>[^/]+)/", row))
    ]
    assert shown_moves == moves
    assert stays_title == "Stay in place: 3"
    assert [row for [row] in shown_stays] == stays
    assert not (folder / "Images").exists()


def _expected(items: list[dict[str, object]]) -> list[tuple[str, list[list[str]]]]:
    """``autostart list --json``'s items as the Autostart page groups and shows them."""
    groups: dict[str, list[list[str]]] = {}
    for item in items:
        source = EN.label(Source(str(item["source"])))
        state = "Enabled" if item["enabled"] else "Disabled"
        cells = [
            str(item["name"]),
            state,
            EN.label(Scope(str(item["scope"]))),
            str(item["location"]),
        ]
        groups.setdefault(source, []).append(cells)
    return [(f"{source}: {len(rows)}", rows) for source, rows in groups.items()]


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
    assert _groups(window.autostart.entries) == _expected(items)


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
    assert _groups(window.autostart.entries) == _expected(items)
