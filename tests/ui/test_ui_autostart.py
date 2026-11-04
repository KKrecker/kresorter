"""The Autostart page: the entries grouped by source, each turned by its switch after a
confirmation that says what is written, every end of a change, the search and the rows' look
(decision 0014, items 3, 13, 24 and 53)."""

import json
import plistlib
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QTreeWidgetItem
from pytestqt.qtbot import QtBot

from fakes import FakeRegistry, deny_stat
from kresorter.autostart.journal import ChangeRefusal, ChangeResult, ChangeState, refused
from kresorter.autostart.models import AutostartItem
from kresorter.autostart.registry import Hive, RegistryError, RegValue, ValueKind
from kresorter.autostart.run_changes import RunKeyChanges
from kresorter.autostart.run_keys import APPROVED, RUN, RUN_ONCE
from kresorter.autostart.xdg_changes import STUB, hidden_copy
from kresorter.core.heuristics import Platform
from kresorter.core.scanner import ScanContext
from kresorter.storage.pending import Domain
from kresorter.ui.dialogs import Confirmation
from kresorter.ui.i18n import Language
from kresorter.ui.parts import BADGE, EMPHASIS, INITIAL, QUIET, SECONDARY, Icon, Switch
from kresorter.ui.sessions import Changed, change_entry
from kresorter.ui.tasks import Task
from kresorter.ui.window import Window
from support.cli import autostart_context, run
from support.files import write
from support.host import native
from support.interrupted import APP
from support.journal import pending_quarantine, query
from support.window import FakeDialogs, children, environment, make_window, wait_idle

OTHER = b"[Desktop Entry]\nType=Application\nName=Other\nExec=/usr/bin/other\n"
SYNC = RegValue("Sync", ValueKind.REG_SZ, r"C:\sync.exe")
SYNC_OFF = RegValue("Sync", ValueKind.REG_BINARY, b"\x03" + bytes(11))


@pytest.fixture
def user(tmp_path: Path) -> Path:
    return tmp_path / "config" / "autostart"


@pytest.fixture
def system(tmp_path: Path) -> Path:
    return tmp_path / "etc" / "xdg" / "autostart"


@pytest.fixture
def dialogs() -> FakeDialogs:
    return FakeDialogs()


def _opened(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    *,
    registry: FakeRegistry | None = None,
    language: Language = "en",
) -> Window:
    """The window on its Autostart page, Linux's or, with ``registry``, Windows'."""
    platform: Platform = "linux" if registry is None else "windows"
    env = environment(tmp_path, zone, data_dir, platform=platform, registry=registry)
    window = make_window(qtbot, env, dialogs=dialogs, language=language)
    window.show_page("autostart")
    wait_idle(qtbot, window)
    return window


def _groups(window: Window) -> list[QTreeWidgetItem]:
    root = window.autostart.entries.invisibleRootItem()
    return children(root)


def _tree(window: Window) -> list[tuple[str, list[tuple[str, ...]]]]:
    """Each group, with what its entries show."""
    return [
        (
            group.text(0),
            [_cells(window, row) for row in children(group)],
        )
        for group in _groups(window)
    ]


def _switch(window: Window, row: QTreeWidgetItem) -> Switch:
    holder = window.autostart.entries.itemWidget(row, 2)
    assert holder is not None
    made = holder.findChild(Switch)
    assert made is not None
    return made


def _lock(window: Window, row: QTreeWidgetItem) -> Icon | None:
    holder = window.autostart.entries.itemWidget(row, 2)
    assert holder is not None
    return holder.findChild(Icon)


def _cells(window: Window, row: QTreeWidgetItem) -> tuple[str, ...]:
    """The entry's name, its state (its switch's tooltip), its scope and its location (the
    name's tooltip)."""
    return row.text(0), _switch(window, row).toolTip(), row.text(1), row.toolTip(0)


def _shown(window: Window) -> tuple[list[str], list[str]]:
    """The groups and the entries the search keeps."""
    groups = [group for group in _groups(window) if not group.isHidden()]
    rows = [row for group in groups for row in children(group)]
    return [group.text(0) for group in groups], [row.text(0) for row in rows if not row.isHidden()]


def _select(window: Window, name: str) -> None:
    window.autostart.entries.clearSelection()
    window.autostart.row(name).setSelected(True)


def _change(qtbot: QtBot, window: Window, name: str, action: str) -> str:
    """A click on the switch of the entry ``name``, on to disable it, off to enable it."""
    page = window.autostart
    switch = page.switch(name)
    assert switch.isChecked() == (action == "disable")
    switch.click()
    wait_idle(qtbot, window)
    return page.result.text()


def _turns(window: Window, name: str) -> tuple[bool, bool]:
    """Whether the entry's switch can be clicked, and whether it is on."""
    switch = window.autostart.switch(name)
    return switch.isEnabled(), switch.isChecked()


def _cli(scan: ScanContext, tmp_path: Path, action: str) -> None:
    """``kresorter autostart <action> <id> --yes`` on the one entry there is."""
    auto = autostart_context("linux", tmp_path)
    _, out, _ = run(["autostart", "list", "--json"], scan, auto)
    (item,) = json.loads(out)["items"]
    assert run(["autostart", action, item["digest"][:12], "--yes"], scan, auto)[0] == 0


def _changes(data_dir: Path) -> list[tuple[object, ...]]:
    return query(data_dir, "SELECT id, action, state FROM autostart_changes")


# --- the entries [0014.24] -----------------------------------------------------------------------


def test_the_entries_are_grouped_by_source_with_state_scope_and_location(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    user: Path,
    system: Path,
) -> None:
    # [0014.24] [0014.2] [0014.53] As `autostart list` reads them: no journal is opened.
    write(user / "app.desktop", APP)
    write(user / "hidden.desktop", hidden_copy(OTHER))
    write(system / "other.desktop", OTHER)
    write(user / "broken.desktop", b"\xff\xfe")
    units = tmp_path / "config" / "systemd" / "user"
    write(units / "sync.service", b"[Service]\nExecStart=/usr/bin/sync-daemon\n")
    (units / "default.target.wants").mkdir()
    (units / "default.target.wants" / "sync.service").symlink_to(units / "sync.service")
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    page = window.autostart
    assert page.entries.isHeaderHidden()
    assert page.entries.accessibleName() == "Autostart entries"
    assert _tree(window) == [
        (
            "Desktop autostart · 3 entries",
            [
                ("app", "Enabled", "This user", str(user / "app.desktop")),
                ("hidden", "Disabled", "This user", str(user / "hidden.desktop")),
                ("other", "Enabled", "All users", str(system / "other.desktop")),
            ],
        ),
        (
            "systemd user service · 1 entry",
            [
                (
                    "sync.service",
                    "Enabled",
                    "This user",
                    str(units / "default.target.wants" / "sync.service"),
                )
            ],
        ),
    ]
    assert page.total.text() == "4 entries, 1 disabled"
    assert page.skipped.text().splitlines() == [
        "Skipped: 1",
        f"Desktop autostart: {user / 'broken.desktop'} (not UTF-8)",
    ]
    assert not data_dir.exists()


def test_the_page_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs, user: Path
) -> None:
    # [0014.24] [0014.53]
    write(user / "app.desktop", APP)
    write(user / "hidden.desktop", hidden_copy(OTHER))
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs, language="ru")
    page = window.autostart
    assert [(group, [row[:3] for row in rows]) for group, rows in _tree(window)] == [
        (
            "Автозапуск рабочего стола · 2 записи",
            [
                ("app", "Включена", "Этот пользователь"),
                ("hidden", "Отключена", "Этот пользователь"),
            ],
        )
    ]
    assert page.total.text() == "2 записи, отключено: 1"
    assert page.skipped.text() == "Пропущено: 0"
    assert (page.refresh_button.text(), page.search.placeholderText()) == (
        "Обновить",
        "Поиск записей",
    )
    assert _change(qtbot, window, "app", "disable") == "Отключено: app (изменение 1)."


def test_windows_entries_are_grouped_by_their_keys(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.24] [0014.53]
    once = RegValue("Setup", ValueKind.REG_SZ, r"C:\setup.exe")
    registry = FakeRegistry({(Hive.HKCU, RUN): [SYNC], (Hive.HKCU, RUN_ONCE): [once]})
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs, registry=registry)
    assert _tree(window) == [
        ("Registry Run · 1 entry", [("Sync", "Enabled", "This user", f"HKCU\\{RUN}\\Sync")]),
        (
            "Registry RunOnce · 1 entry",
            [("Setup", "Enabled", "This user", f"HKCU\\{RUN_ONCE}\\Setup")],
        ),
    ]


def test_refresh_reads_what_changed_since(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    user: Path,
    scan: ScanContext,
) -> None:
    # [0014.24] Disabled by the CLI while the window was open.
    write(user / "app.desktop", APP)
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    _cli(scan, tmp_path, "disable")
    window.autostart.refresh_button.click()
    wait_idle(qtbot, window)
    assert _tree(window)[0][1][0][:2] == ("app", "Disabled")


# --- what can change [0014.24] -------------------------------------------------------------------


def test_the_switch_of_an_entry_that_can_change_is_on_while_it_starts(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    user: Path,
    system: Path,
) -> None:
    # [0014.24] [0014.53] A group is no entry and cannot be selected.
    write(user / "app.desktop", APP)
    write(user / "hidden.desktop", hidden_copy(OTHER))
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    page = window.autostart
    assert (_turns(window, "app"), _turns(window, "hidden")) == ((True, True), (True, False))
    assert [page.switch(name).accessibleName() for name in ("app", "hidden")] == ["app", "hidden"]
    _groups(window)[0].setSelected(True)
    assert page.entries.selectedItems() == []


def test_an_entry_that_cannot_change_has_a_lock_and_a_switch_that_cannot_turn(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.24] [0014.53] RunOnce values are read only (0011).
    once = RegValue("Setup", ValueKind.REG_SZ, r"C:\setup.exe")
    registry = FakeRegistry({(Hive.HKCU, RUN): [SYNC], (Hive.HKCU, RUN_ONCE): [once]})
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs, registry=registry)
    page = window.autostart
    assert (_turns(window, "Setup"), _turns(window, "Sync")) == ((False, True), (True, True))
    locks = [_lock(window, page.row(name)) for name in ("Setup", "Sync")]
    assert [(lock.name, lock.toolTip()) for lock in locks if lock is not None] == [
        ("lock", "Listed only: kresorter does not change this entry")
    ]
    assert locks[1] is None
    QTest.mouseClick(page.switch("Setup"), Qt.MouseButton.LeftButton)
    wait_idle(qtbot, window)
    assert (dialogs.asked, _turns(window, "Setup")) == ([], (False, True))


# --- the confirmation [0014.3] [0014.24] ---------------------------------------------------------


def test_a_disable_asks_first_saying_what_is_written_and_a_cancel_changes_nothing(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    user: Path,
    system: Path,
) -> None:
    # [0014.3] [0014.24] As `autostart disable` without --yes: nothing is opened.
    entry = write(user / "app.desktop", APP)
    other = write(system / "other.desktop", OTHER)
    dialogs.answer = False
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    assert _change(qtbot, window, "app", "disable") == ""
    assert _change(qtbot, window, "other", "disable") == ""
    assert _turns(window, "app") == (True, True)  # [0014.53] it turns once the entry has
    assert dialogs.asked == [
        Confirmation(
            title="Disable app",
            text="Disable app (Desktop autostart, This user)?",
            details=(
                f"Location: {entry}",
                "Its file is replaced by a copy with Hidden=true; the original is kept in the"
                " autostart store.",
            ),
            action="Disable",
        ),
        Confirmation(
            title="Disable other",
            text="Disable other (Desktop autostart, All users)?",
            details=(
                f"Location: {other}",
                f"A stub with Hidden=true is created in {user}; the system file is never written.",
            ),
            action="Disable",
        ),
    ]
    assert (entry.read_bytes(), other.read_bytes()) == (APP, OTHER)
    assert sorted(user.iterdir()) == [entry]
    assert not data_dir.exists()


def test_an_enable_asks_first_saying_nothing_is_deleted(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs, user: Path
) -> None:
    # [0014.3] [0014.24]
    entry = write(user / "app.desktop", hidden_copy(APP))
    dialogs.answer = False
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    assert _change(qtbot, window, "app", "enable") == ""
    assert dialogs.asked == [
        Confirmation(
            title="Enable app",
            text="Enable app (Desktop autostart, This user)?",
            details=(
                f"Location: {entry}",
                "If kresorter disabled it, what it changed is put back (the original from the"
                " store, or the stub moved to the store); nothing is deleted.",
            ),
            action="Enable",
        )
    ]
    assert not data_dir.exists()


@pytest.mark.parametrize(
    ("flags", "action", "how"),
    [
        (
            [],
            "disable",
            "Its StartupApproved flag is set to disabled, as the Task Manager does; the Run"
            " value is never written.",
        ),
        (
            [SYNC_OFF],
            "enable",
            "Its StartupApproved flag is set to enabled; the Run value is never written.",
        ),
    ],
)
def test_a_run_value_s_confirmation_says_its_flag_is_written(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    flags: list[RegValue],
    action: str,
    how: str,
) -> None:
    # [0014.3] [0014.24]
    registry = FakeRegistry({(Hive.HKCU, RUN): [SYNC], (Hive.HKCU, APPROVED): flags})
    dialogs.answer = False
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs, registry=registry)
    _change(qtbot, window, "Sync", action)
    [asked] = dialogs.asked
    assert asked.details == (f"Location: HKCU\\{RUN}\\Sync", how)
    assert registry.writes == []


# --- the result [0014.24] ------------------------------------------------------------------------


def test_disable_then_enable_an_entry(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs, user: Path
) -> None:
    # [0014.24] [0014.53] A click on its switch selects the entry, and it stays selected.
    entry = write(user / "app.desktop", APP)
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    assert _change(qtbot, window, "app", "disable") == "Disabled app (change 1)."
    assert entry.read_bytes() == hidden_copy(APP)
    assert _tree(window)[0][1][0][:2] == ("app", "Disabled")
    assert window.autostart.total.text() == "1 entry, 1 disabled"
    assert _turns(window, "app") == (True, False)
    item = window.autostart.selected()
    assert item is not None
    assert item.name == "app"
    assert _change(qtbot, window, "app", "enable") == "Enabled app (change 2)."
    assert _turns(window, "app") == (True, True)
    assert entry.read_bytes() == APP
    assert _changes(data_dir) == [(1, "disable", "done"), (2, "enable", "done")]
    assert window.recovery.isHidden()


def test_a_system_entry_is_disabled_by_a_stub(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    user: Path,
    system: Path,
) -> None:
    # [0014.24]
    other = write(system / "other.desktop", OTHER)
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    assert _change(qtbot, window, "other", "disable") == "Disabled other (change 1)."
    assert (user / "other.desktop").read_bytes() == STUB
    assert other.read_bytes() == OTHER
    assert _tree(window)[0][1] == [("other", "Disabled", "This user", str(user / "other.desktop"))]


def test_a_refused_change_says_why(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs, user: Path
) -> None:
    # [0014.24] Disabled, but not by kresorter: enabling it would edit it (0011 item 74).
    entry = write(user / "app.desktop", hidden_copy(APP))
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    assert _change(qtbot, window, "app", "enable") == "Refused: Not disabled by kresorter."
    assert entry.read_bytes() == hidden_copy(APP)
    assert _changes(data_dir) == []


def test_an_entry_changed_since_it_was_listed_is_not_changed(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs, user: Path
) -> None:
    # [0014.24] Changed while the dialog was open; the list shows it as it is now.
    entry = write(user / "app.desktop", APP)
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    dialogs.meanwhile.append(lambda: write(entry, OTHER))
    assert _change(qtbot, window, "app", "disable") == "Refused: Changed since it was listed."
    assert entry.read_bytes() == OTHER
    assert _tree(window)[0][1] == [("app", "Enabled", "This user", str(entry))]
    assert window.autostart.selected() is not None


def test_an_entry_gone_since_it_was_listed_leaves_nothing_selected(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs, user: Path
) -> None:
    # [0014.24]
    entry = write(user / "app.desktop", APP)
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    dialogs.meanwhile.append(lambda: entry.rename(user / "renamed.desktop"))
    assert _change(qtbot, window, "app", "disable") == "Refused: Changed since it was listed."
    assert [row[0] for row in _tree(window)[0][1]] == ["renamed"]
    assert window.autostart.selected() is None
    assert window.autostart.explain.isHidden()


def test_a_rolled_back_change_says_so(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.24]
    error = RegistryError("Access is denied")
    registry = FakeRegistry({(Hive.HKCU, RUN): [SYNC]}, write_error=error)
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs, registry=registry)
    assert _change(qtbot, window, "Sync", "disable") == (
        "Not changed: Access is denied; it was rolled back (change 1)."
    )
    assert window.recovery.isHidden()


def test_a_failed_change_names_recover_and_the_banner_offers_it(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0014.24] [0014.25]
    def failed(self: RunKeyChanges, item: AutostartItem) -> ChangeResult:
        return ChangeResult(7, ChangeState.FAILED, None, "the flag is something else")

    monkeypatch.setattr(RunKeyChanges, "disable", failed)
    registry = FakeRegistry({(Hive.HKCU, RUN): [SYNC]})
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs, registry=registry)
    assert _change(qtbot, window, "Sync", "disable") == (
        "Change 7 failed: the flag is something else. Use Recover."
    )
    banner = window.recovery
    assert not banner.isHidden()
    assert banner.text.text() == "Unfinished work: Autostart."
    assert not banner.recover_button.isHidden()


def test_a_change_that_cannot_be_read_back_is_left_for_recover(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0014.24] [0014.25]
    def unreadable(self: RunKeyChanges, item: AutostartItem) -> ChangeResult:
        raise RegistryError("access denied")

    monkeypatch.setattr(RunKeyChanges, "disable", unreadable)
    registry = FakeRegistry({(Hive.HKCU, RUN): [SYNC]})
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs, registry=registry)
    assert _change(qtbot, window, "Sync", "disable") == (
        "An unfinished autostart change cannot be checked: access denied. Fix or move what is"
        " there, then use Recover again."
    )
    assert window.recovery.offered == {Domain.AUTOSTART}


def test_a_check_before_the_change_that_fails_changes_nothing(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    user: Path,
    system: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0014.24] Where the stub would go: its device cannot be known.
    write(system / "app.desktop", APP)
    user.mkdir(parents=True)
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    deny_stat(monkeypatch, user)
    window.autostart.switch("app").click()
    wait_idle(qtbot, window)
    monkeypatch.undo()
    assert window.autostart.result.text() == (
        f"Cannot change app: [Errno 13] Permission denied: {str(user)!r}; nothing was changed."
    )
    assert list(user.iterdir()) == []
    assert _changes(data_dir) == []


def test_nothing_is_changed_on_macos(
    tmp_path: Path, scan: ScanContext, data_dir: Path, qtbot: QtBot, zone: Path
) -> None:
    # [0014.24] [0014.53] No entry there can change: no switch turns, and a change is refused.
    agent = {"Label": "com.example.agent", "ProgramArguments": ["/usr/bin/agent"]}
    write(tmp_path / "Library" / "LaunchAgents" / "agent.plist", plistlib.dumps(agent))
    window = make_window(qtbot, environment(tmp_path, zone, data_dir, platform="darwin"))
    window.show_page("autostart")
    wait_idle(qtbot, window)
    _select(window, "com.example.agent")
    assert _turns(window, "com.example.agent") == (False, True)
    auto = autostart_context("darwin", tmp_path)
    item = window.autostart.selected()
    assert item is not None
    changed = change_entry(scan, auto, "disable", item)
    assert isinstance(changed, Changed)
    assert changed.result == refused(ChangeRefusal.READ_ONLY, "launch_agent entries are read-only")
    assert _changes(data_dir) == []


# --- recovery first [0014.13] --------------------------------------------------------------------


def test_an_interrupted_change_is_recovered_first(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    user: Path,
    scan: ScanContext,
) -> None:
    # [0014.13] As `autostart enable` reports it; Recover is no longer offered.
    write(user / "app.desktop", APP)
    _cli(scan, tmp_path, "disable")
    query(data_dir, "UPDATE autostart_changes SET state = 'pending', finished_at_ns = NULL")
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    assert window.recovery.offered == {Domain.AUTOSTART}
    assert _change(qtbot, window, "app", "enable") == "Enabled app (change 2)."
    banner = window.recovery
    assert banner.text.text().splitlines() == [
        "Recovered interrupted autostart changes: 1",
        "Change 1: Done.",
    ]
    assert (banner.offered, banner.recover_button.isHidden()) == (frozenset(), True)


def test_an_interrupted_change_that_cannot_be_checked_stops_the_change(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    user: Path,
    system: Path,
    scan: ScanContext,
) -> None:
    # [0014.13] [0014.25]
    entry = write(user / "app.desktop", APP)
    _cli(scan, tmp_path, "disable")
    query(data_dir, "UPDATE autostart_changes SET state = 'pending', finished_at_ns = NULL")
    other = write(system / "other.desktop", OTHER)
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    entry.rename(tmp_path / "elsewhere")
    entry.mkdir()
    assert _change(qtbot, window, "other", "disable") == (
        "An unfinished autostart change cannot be checked: not a regular file. Fix or move what"
        " is there, then use Recover again."
    )
    assert other.read_bytes() == OTHER
    assert sorted(user.iterdir()) == [entry]
    assert window.recovery.offered == {Domain.AUTOSTART}
    assert _changes(data_dir) == [(1, "disable", "pending")]


def test_unfinished_work_of_another_domain_comes_first(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs, user: Path
) -> None:
    # [0014.13] [0014.25]
    entry = write(user / "app.desktop", APP)
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    pending_quarantine(data_dir)
    assert _change(qtbot, window, "app", "disable") == (
        "Unfinished work (Quarantine) comes first: nothing was changed. Use Recover."
    )
    assert entry.read_bytes() == APP
    assert _changes(data_dir) == []
    assert window.recovery.offered == {Domain.QUARANTINE}
    assert window.recovery.text.text() == "Unfinished work: Quarantine."


# --- the page [0014.53] --------------------------------------------------------------------------


def test_a_row_has_a_tile_with_its_initial_its_location_under_its_name_and_its_scope_as_a_badge(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    user: Path,
    system: Path,
    home: Path,
) -> None:
    # [0014.53] The location from the home folder as ~, the whole in its tooltip; a section's
    # name and count in semibold secondary text.
    write(user / "app.desktop", APP)
    write(system / "other.desktop", OTHER)
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    page = window.autostart
    row = page.row("app")
    assert [row.data(0, role) for role in (INITIAL, EMPHASIS, SECONDARY)] == [
        "A",
        True,
        native("~/config/autostart/app.desktop"),
    ]
    assert row.toolTip(0) == str(user / "app.desktop")
    assert [page.row(name).data(1, BADGE) for name in ("app", "other")] == ["advisory"] * 2
    assert page.row("other").text(1) == "All users"
    (group,) = _groups(window)
    assert (group.data(0, EMPHASIS), group.data(0, QUIET)) == (True, True)
    assert group.flags() == Qt.ItemFlag.ItemIsEnabled
    assert (page.entries.rootIsDecorated(), page.entries.itemsExpandable()) == (False, False)


def test_the_search_keeps_the_entries_whose_name_or_location_contains_its_text(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    user: Path,
    system: Path,
) -> None:
    # [0014.53] Ignoring case, with the sections that keep one; an entry put away is no longer
    # selected, and a refresh keeps the search.
    write(user / "app.desktop", APP)
    write(system / "other.desktop", OTHER)
    units = tmp_path / "config" / "systemd" / "user"
    write(units / "sync.service", b"[Service]\nExecStart=/usr/bin/sync-daemon\n")
    (units / "default.target.wants").mkdir()
    (units / "default.target.wants" / "sync.service").symlink_to(units / "sync.service")
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    page = window.autostart
    desktop, systemd = "Desktop autostart · 2 entries", "systemd user service · 1 entry"
    assert page.search.placeholderText() == "Search entries"
    assert _shown(window) == ([desktop, systemd], ["app", "other", "sync.service"])
    page.search.setText("APP.DESKTOP")  # not "APP": Windows' temporary files are in AppData
    assert _shown(window) == ([desktop], ["app"])
    page.search.setText(native("ETC/xdg"))
    assert _shown(window) == ([desktop], ["other"])
    page.search.setText("Sync")
    assert _shown(window) == ([systemd], ["sync.service"])
    _select(window, "sync.service")
    page.search.setText("nothing like it")
    assert _shown(window) == ([], [])
    assert (page.selected(), page.detail.text(), page.explain.isHidden()) == (None, "", True)
    page.search.setText("other")
    page.refresh_button.click()
    wait_idle(qtbot, window)
    assert _shown(window) == ([desktop], ["other"])
    page.search.clear()
    assert _shown(window) == ([desktop, systemd], ["app", "other", "sync.service"])


def test_no_switch_turns_while_a_task_runs(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.53] [0014.16] And when it ends, a locked one still does not.
    once = RegValue("Setup", ValueKind.REG_SZ, r"C:\setup.exe")
    registry = FakeRegistry({(Hive.HKCU, RUN): [SYNC], (Hive.HKCU, RUN_ONCE): [once]})
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs, registry=registry)
    release = threading.Event()
    assert window.run(Task("Scanning", lambda: release.wait(timeout=10), lambda _: None))
    assert (_turns(window, "Sync"), _turns(window, "Setup")) == ((False, True), (False, True))
    release.set()
    qtbot.waitUntil(lambda: window.autostart.switch("Sync").isEnabled())
    assert _turns(window, "Setup") == (False, True)


def test_the_detail_and_explain_are_under_the_list_once_an_entry_is_selected(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs, user: Path
) -> None:
    # [0014.53] [0014.26] The total and the skips in secondary text.
    write(user / "app.desktop", APP)
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    page = window.autostart
    layout = page.layout()
    assert layout is not None
    order = [page.entries, page.detail, page.explain, page.result, page.total, page.skipped]
    places = [layout.indexOf(part) for part in order]
    assert places == sorted(places)
    assert places[0] >= 0
    assert page.explain.isHidden()
    _select(window, "app")
    assert not page.explain.isHidden()
    assert page.detail.text() == "Command: /usr/bin/app --tray"
    page.entries.clearSelection()
    assert page.explain.isHidden()
    assert [page.total.property("role"), page.skipped.property("role")] == ["secondary"] * 2
