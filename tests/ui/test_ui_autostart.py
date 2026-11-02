"""The Autostart page: the entries grouped by source, Disable and Enable after a confirmation
that says what is written, and every end of a change (decision 0014, items 3, 13 and 24)."""

import json
import plistlib
from pathlib import Path

import pytest
from PySide6.QtWidgets import QTreeWidgetItem
from pytestqt.qtbot import QtBot

from fakes import FakeRegistry, deny_stat
from safeclean.autostart.journal import ChangeRefusal, ChangeResult, ChangeState, refused
from safeclean.autostart.models import AutostartItem
from safeclean.autostart.registry import Hive, RegistryError, RegValue, ValueKind
from safeclean.autostart.run_changes import RunKeyChanges
from safeclean.autostart.run_keys import APPROVED, RUN, RUN_ONCE
from safeclean.autostart.xdg_changes import STUB, hidden_copy
from safeclean.core.heuristics import Platform
from safeclean.core.scanner import ScanContext
from safeclean.storage.pending import Domain
from safeclean.ui.dialogs import Confirmation
from safeclean.ui.i18n import Language
from safeclean.ui.sessions import Changed, change_entry
from safeclean.ui.window import Window
from support.cli import autostart_context, run
from support.files import write
from support.interrupted import APP
from support.journal import pending_quarantine, query
from support.window import FakeDialogs, environment, make_window, wait_idle

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


def _child(item: QTreeWidgetItem, index: int) -> QTreeWidgetItem:
    child = item.child(index)
    assert child is not None
    return child


def _tree(window: Window) -> list[tuple[str, list[tuple[str, ...]]]]:
    """Each group, with the cells of its entries."""
    root = window.autostart.entries.invisibleRootItem()
    groups = [_child(root, index) for index in range(root.childCount())]
    return [
        (group.text(0), [_cells(_child(group, index)) for index in range(group.childCount())])
        for group in groups
    ]


def _cells(row: QTreeWidgetItem) -> tuple[str, ...]:
    return tuple(row.text(column) for column in range(4))


def _select(window: Window, name: str) -> None:
    window.autostart.entries.clearSelection()
    window.autostart.row(name).setSelected(True)


def _change(qtbot: QtBot, window: Window, name: str, action: str) -> str:
    _select(window, name)
    page = window.autostart
    (page.disable_button if action == "disable" else page.enable_button).click()
    wait_idle(qtbot, window)
    return page.result.text()


def _buttons(window: Window) -> tuple[bool, bool]:
    return window.autostart.disable_button.isEnabled(), window.autostart.enable_button.isEnabled()


def _cli(scan: ScanContext, tmp_path: Path, action: str) -> None:
    """``safeclean autostart <action> <id> --yes`` on the one entry there is."""
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
    # [0014.24] [0014.2] As `autostart list` reads them: no journal is opened.
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
    header = page.entries.headerItem()
    assert [header.text(column) for column in range(4)] == ["Name", "State", "Scope", "Location"]
    assert page.entries.accessibleName() == "Autostart entries"
    assert _tree(window) == [
        (
            "Desktop autostart: 3",
            [
                ("app", "Enabled", "This user", str(user / "app.desktop")),
                ("hidden", "Disabled", "This user", str(user / "hidden.desktop")),
                ("other", "Enabled", "All users", str(system / "other.desktop")),
            ],
        ),
        (
            "systemd user service: 1",
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
    # [0014.24]
    write(user / "app.desktop", APP)
    write(user / "hidden.desktop", hidden_copy(OTHER))
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs, language="ru")
    page = window.autostart
    header = page.entries.headerItem()
    assert [header.text(column) for column in range(4)] == [
        "Название",
        "Состояние",
        "Область",
        "Расположение",
    ]
    assert [(group, [row[:3] for row in rows]) for group, rows in _tree(window)] == [
        (
            "Автозапуск рабочего стола: 2",
            [
                ("app", "Включена", "Этот пользователь"),
                ("hidden", "Отключена", "Этот пользователь"),
            ],
        )
    ]
    assert page.total.text() == "2 записи, отключено: 1"
    assert page.skipped.text() == "Пропущено: 0"
    assert (page.refresh_button.text(), page.disable_button.text()) == ("Обновить", "Отключить…")
    assert page.enable_button.text() == "Включить…"
    assert _change(qtbot, window, "app", "disable") == "Отключено: app (изменение 1)."


def test_windows_entries_are_grouped_by_their_keys(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.24]
    once = RegValue("Setup", ValueKind.REG_SZ, r"C:\setup.exe")
    registry = FakeRegistry({(Hive.HKCU, RUN): [SYNC], (Hive.HKCU, RUN_ONCE): [once]})
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs, registry=registry)
    assert _tree(window) == [
        ("Registry Run: 1", [("Sync", "Enabled", "This user", f"HKCU\\{RUN}\\Sync")]),
        ("Registry RunOnce: 1", [("Setup", "Enabled", "This user", f"HKCU\\{RUN_ONCE}\\Setup")]),
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


def test_disable_and_enable_are_offered_for_an_entry_that_can_change(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    user: Path,
    system: Path,
) -> None:
    # [0014.24] A group is no entry and cannot be selected.
    write(user / "app.desktop", APP)
    write(user / "hidden.desktop", hidden_copy(OTHER))
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    page = window.autostart
    assert _buttons(window) == (False, False)
    _child(page.entries.invisibleRootItem(), 0).setSelected(True)
    assert (page.entries.selectedItems(), _buttons(window)) == ([], (False, False))
    _select(window, "app")
    assert _buttons(window) == (True, False)
    _select(window, "hidden")
    assert _buttons(window) == (False, True)
    page.entries.clearSelection()
    assert _buttons(window) == (False, False)


def test_an_entry_that_cannot_change_offers_neither(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.24] RunOnce values are read only (0011).
    once = RegValue("Setup", ValueKind.REG_SZ, r"C:\setup.exe")
    registry = FakeRegistry({(Hive.HKCU, RUN_ONCE): [once]})
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs, registry=registry)
    _select(window, "Setup")
    assert _buttons(window) == (False, False)


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
                "If safeclean disabled it, what it changed is put back (the original from the"
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
    # [0014.24] The entry stays selected: Enable puts it back.
    entry = write(user / "app.desktop", APP)
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    assert _change(qtbot, window, "app", "disable") == "Disabled app (change 1)."
    assert entry.read_bytes() == hidden_copy(APP)
    assert _tree(window)[0][1][0][:2] == ("app", "Disabled")
    assert window.autostart.total.text() == "1 entry, 1 disabled"
    assert _buttons(window) == (False, True)
    window.autostart.enable_button.click()
    wait_idle(qtbot, window)
    assert window.autostart.result.text() == "Enabled app (change 2)."
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
    # [0014.24] Disabled, but not by safeclean: enabling it would edit it (0011 item 74).
    entry = write(user / "app.desktop", hidden_copy(APP))
    window = _opened(qtbot, tmp_path, zone, data_dir, dialogs)
    assert _change(qtbot, window, "app", "enable") == "Refused: Not disabled by safeclean."
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
    assert _buttons(window) == (False, False)


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
    _select(window, "app")
    deny_stat(monkeypatch, user)
    window.autostart.disable_button.click()
    wait_idle(qtbot, window)
    monkeypatch.undo()
    assert window.autostart.result.text() == (
        f"Cannot change app: [Errno 13] Permission denied: '{user}'; nothing was changed."
    )
    assert list(user.iterdir()) == []
    assert _changes(data_dir) == []


def test_nothing_is_changed_on_macos(
    tmp_path: Path, scan: ScanContext, data_dir: Path, qtbot: QtBot, zone: Path
) -> None:
    # [0014.24] No entry there can change: the page offers neither, and a change is refused.
    agent = {"Label": "com.example.agent", "ProgramArguments": ["/usr/bin/agent"]}
    write(tmp_path / "Library" / "LaunchAgents" / "agent.plist", plistlib.dumps(agent))
    window = make_window(qtbot, environment(tmp_path, zone, data_dir, platform="darwin"))
    window.show_page("autostart")
    wait_idle(qtbot, window)
    _select(window, "com.example.agent")
    assert _buttons(window) == (False, False)
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
