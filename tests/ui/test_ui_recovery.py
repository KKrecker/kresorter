"""Report first, every action confirmed, recovery first, and the banner that offers Recover
(decision 0014, items 2, 3, 13 and 25)."""

import errno
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from safeclean.autostart.changes import XdgChanges
from safeclean.autostart.journal import ChangeRecovery
from safeclean.core.scanner import ScanContext
from safeclean.organize import recovery as organize_recovery
from safeclean.organize.journal import BatchKind, BatchState
from safeclean.organize.recovery import RecoveredBatch
from safeclean.quarantine.recovery import RecoveryReport
from safeclean.storage.lock import InstanceLock
from safeclean.storage.pending import Domain
from safeclean.ui.dialogs import Confirmation
from safeclean.ui.i18n import Language, Translator
from safeclean.ui.recovery import autostart_lines, organize_lines, quarantine_lines
from safeclean.ui.sessions import Unclosed
from safeclean.ui.window import Window
from support.cli import autostart_context, run
from support.files import write
from support.interrupted import (
    APP,
    crashed_batch,
    interrupted_xdg_disable,
    left_pending,
    quarantined,
)
from support.journal import pending_move_batch, pending_quarantine, query
from support.moves import MOVED, A, B, C, three_files, tree
from support.window import FakeDialogs, environment, junk_tree, make_window, scanned, wait_idle

QUARANTINE = (
    "Quarantine: each interrupted move, restore or deletion is closed by where its files are now."
)
ORGANIZE = (
    "Organize: each interrupted batch is closed by where its files are now; no file is moved."
)
AUTOSTART = (
    "Autostart: each interrupted change is completed or put back, by what its entry holds now."
)
UNCHECKED = (
    "An unfinished autostart change cannot be checked: not a regular file. Fix or move what is"
    " there, then use Recover again."
)


@pytest.fixture
def dialogs() -> FakeDialogs:
    return FakeDialogs()


def _window(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    language: Language = "en",
) -> Window:
    env = environment(tmp_path, zone, data_dir)
    return make_window(qtbot, env, dialogs=dialogs, language=language)


def _banner(window: Window) -> list[str]:
    return window.recovery.text.text().splitlines()


def _recover(qtbot: QtBot, window: Window) -> None:
    window.recovery.recover_button.click()
    wait_idle(qtbot, window)


def _opened(qtbot: QtBot, window: Window, page: str) -> None:
    window.show_page(page)
    wait_idle(qtbot, window)


def _users(tmp_path: Path) -> dict[str, bytes | str]:
    """Every file, folder and link under tmp_path but the data directory's."""
    return {name: found for name, found in tree(tmp_path).items() if name.split("/")[0] != "data"}


def _offered(window: Window) -> bool:
    banner = window.recovery
    return not banner.isHidden() and not banner.recover_button.isHidden()


# --- report first [0014.2] -----------------------------------------------------------------------


def test_opening_the_window_creates_no_data_directory_and_no_journal(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.2]
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    assert not data_dir.exists()
    assert window.recovery.isHidden()


def test_scanning_planning_and_every_listing_change_no_file_of_the_user(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.2] Only the Quarantine and Organize pages open the journal, as `quarantine list` and
    # `organize list` do.
    junk_tree(zone)
    folder = three_files(zone)
    write(tmp_path / "config" / "autostart" / "app.desktop", APP)
    before = _users(tmp_path)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    scanned(qtbot, window)
    assert window.findings.findings()
    _opened(qtbot, window, "autostart")
    window.autostart.refresh_button.click()
    wait_idle(qtbot, window)
    assert window.autostart.total.text() == "1 entry, 0 disabled"
    assert not data_dir.exists()
    _opened(qtbot, window, "quarantine")
    _opened(qtbot, window, "organize")
    dialogs.folders.append(folder)
    window.organize.choose_button.click()
    wait_idle(qtbot, window)
    assert window.organize.move_button.isEnabled()
    assert _users(tmp_path) == before
    assert (data_dir / "journal.db").is_file()


def test_a_journal_with_unfinished_work_is_only_looked_into(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.2] [0014.25] The banner names the domains and offers Recover; nothing is closed.
    pending_quarantine(data_dir)
    pending_move_batch(data_dir)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    assert _offered(window)
    assert _banner(window) == ["Unfinished work: Quarantine, Organize."]
    assert window.recovery.offered == {Domain.QUARANTINE, Domain.ORGANIZE}
    assert window.recovery.recover_button.isEnabled()
    assert query(data_dir, "SELECT state FROM operations") == [("pending",)]
    assert query(data_dir, "SELECT state FROM move_batches") == [("pending",)]


def test_a_journal_without_unfinished_work_shows_no_banner(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    scan: ScanContext,
) -> None:
    # [0014.25]
    assert run(["recover"], scan, autostart_context("linux", tmp_path))[0] == 0
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    assert window.recovery.isHidden()


def test_a_journal_that_cannot_be_read_now_shows_no_banner(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.25] The session that needs it will say why.
    write(data_dir / "journal.db", b"not a journal")
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    assert window.recovery.isHidden()
    assert (data_dir / "journal.db").read_bytes() == b"not a journal"


def test_a_data_directory_that_must_not_be_used_is_not_looked_into(
    qtbot: QtBot, tmp_path: Path, zone: Path, dialogs: FakeDialogs
) -> None:
    # [0014.2] Inside a scan zone (0009): nothing is opened there.
    inside = zone / "data"
    pending_quarantine(inside)
    window = _window(qtbot, tmp_path, zone, inside, dialogs)
    assert window.recovery.isHidden()
    assert sorted(path.name for path in inside.iterdir()) == ["journal.db"]


# --- Recover [0014.3] [0014.13] [0014.25] --------------------------------------------------------


def test_recover_asks_first_and_a_cancel_recovers_nothing(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.3] It shows the work recovery finishes.
    pending_quarantine(data_dir)
    pending_move_batch(data_dir)
    dialogs.answer = False
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    _recover(qtbot, window)
    assert dialogs.asked == [
        Confirmation(
            title="Recover",
            text="Finish the unfinished work (Quarantine, Organize) by what is on the disk now?",
            details=(QUARANTINE, ORGANIZE),
            action="Recover",
        )
    ]
    assert query(data_dir, "SELECT state FROM operations") == [("pending",)]
    assert query(data_dir, "SELECT state FROM move_batches") == [("pending",)]
    assert _banner(window) == ["Unfinished work: Quarantine, Organize."]


def test_recover_closes_every_domain_as_safeclean_recover_does(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    scan: ScanContext,
) -> None:
    # [0014.13] [0014.25] The quarantine first, then organize, then autostart; after it,
    # `safeclean recover` finds nothing.
    quarantined(scan, zone)
    interrupted_xdg_disable(tmp_path, data_dir)
    left_pending(data_dir)
    crashed_batch(zone, data_dir, {A: "exit-before"})
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    assert _banner(window) == ["Unfinished work: Quarantine, Organize, Autostart."]
    _recover(qtbot, window)
    [asked] = dialogs.asked
    assert asked.details == (QUARANTINE, ORGANIZE, AUTOSTART)
    assert _banner(window) == [
        "Recovered an interrupted quarantine operation (1 file).",
        "Recovered interrupted organize batches: 1",
        "Batch 1: Rolled back.",
        "Recovered interrupted autostart changes: 1",
        "Change 1: Done.",
    ]
    assert window.recovery.offered == frozenset()
    assert window.recovery.recover_button.isHidden()
    auto = autostart_context("linux", tmp_path)
    assert run(["recover"], scan, auto) == (0, "Nothing to recover.\n", "")


def test_recover_in_russian(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.25]
    folder = crashed_batch(zone, data_dir, {C: "exit-before"})
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs, language="ru")
    banner = window.recovery
    assert (banner.recover_button.text(), banner.hide_button.text()) == (
        "Восстановить после сбоя…",
        "Скрыть",
    )
    assert _banner(window) == ["Прерванная работа: Сортировка."]
    _recover(qtbot, window)
    [asked] = dialogs.asked
    assert (asked.title, asked.action) == ("Восстановить", "Восстановить")
    assert asked.text == "Завершить прерванную работу (Сортировка) по тому, что сейчас на диске?"
    assert asked.details == (Translator("ru").text("recover.organize"),)
    assert asked.details[0].startswith("Сортировка: каждый прерванный пакет закрывается")
    failed = Translator("ru").label(BatchState.FAILED)
    assert _banner(window) == [
        "Восстановлено прерванных пакетов сортировки: 1",
        f"Пакет 1: {failed}.",
        f"Остался разложенным: {folder / MOVED[A]}",
        f"Остался разложенным: {folder / MOVED[B]}",
        "Возврат пакета 1 вернёт их на место.",
    ]


def test_an_autostart_change_that_cannot_be_checked_stays_offered(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    scan: ScanContext,
) -> None:
    # [0014.13] [0014.25] The quarantine is recovered all the same.
    quarantined(scan, zone)
    entry = interrupted_xdg_disable(tmp_path, data_dir)
    left_pending(data_dir)
    entry.rename(tmp_path / "elsewhere")
    entry.mkdir()
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    _recover(qtbot, window)
    assert _banner(window) == [
        "Recovered an interrupted quarantine operation (1 file).",
        UNCHECKED,
        "Unfinished work: Autostart.",
    ]
    assert window.recovery.offered == {Domain.AUTOSTART}
    assert _offered(window)
    assert query(data_dir, "SELECT state FROM operations") == [("done",)]
    assert query(data_dir, "SELECT state FROM autostart_changes") == [("pending",)]


def test_an_autostart_change_that_cannot_be_closed_says_why(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0014.25] What it has to move cannot be moved.
    interrupted_xdg_disable(tmp_path, data_dir)

    def unmovable(self: XdgChanges) -> ChangeRecovery:
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(XdgChanges, "recover", unmovable)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    _recover(qtbot, window)
    assert _banner(window) == [
        "An unfinished autostart change cannot be closed: [Errno 13] Permission denied. Fix or"
        " move what is there, then use Recover again.",
        "Unfinished work: Autostart.",
    ]


def test_nothing_to_recover(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.25] An operation that had moved no file yet.
    pending_quarantine(data_dir)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    _recover(qtbot, window)
    assert _banner(window) == ["Nothing to recover."]
    assert not window.recovery.isHidden()
    assert window.recovery.recover_button.isHidden()
    assert query(data_dir, "SELECT state FROM operations") != [("pending",)]


def test_a_recovery_that_cannot_run_says_why(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.25] Another safeclean holds the lock: Recover is still offered.
    pending_quarantine(data_dir)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    with InstanceLock(data_dir / "safeclean.lock"):
        _recover(qtbot, window)
    assert _banner(window) == [
        f"safeclean is busy elsewhere: another safeclean is using {data_dir}; try again later",
        "Unfinished work: Quarantine.",
    ]
    assert query(data_dir, "SELECT state FROM operations") == [("pending",)]


def test_hide_hides_the_banner_and_a_domain_recovered_by_its_page_is_no_longer_offered(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.13] [0014.25]
    pending_quarantine(data_dir)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    window.recovery.hide_button.click()
    assert window.recovery.isHidden()
    _opened(qtbot, window, "quarantine")
    assert (window.recovery.offered, window.recovery.isHidden()) == (frozenset(), True)
    assert query(data_dir, "SELECT state FROM operations") != [("pending",)]


# --- recovery first [0014.13] --------------------------------------------------------------------


def test_the_quarantine_page_recovers_the_quarantine_first(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    scan: ScanContext,
) -> None:
    # [0014.13] As `quarantine list` reports it.
    quarantined(scan, zone)
    left_pending(data_dir)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    _opened(qtbot, window, "quarantine")
    assert _banner(window) == ["Recovered an interrupted quarantine operation (1 file)."]
    assert window.recovery.recover_button.isHidden()
    assert window.quarantine.total.text() == "In the quarantine: 1 file, 7 B"


def test_moving_findings_recovers_the_quarantine_first(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    scan: ScanContext,
) -> None:
    # [0014.13]
    quarantined(scan, zone)
    left_pending(data_dir)
    junk_tree(zone)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    scanned(qtbot, window)
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    assert _banner(window) == ["Recovered an interrupted quarantine operation (1 file)."]
    assert window.findings.result.text().startswith("Moved to the quarantine: 3 files")


def test_the_organize_page_recovers_organize_first(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.13] As `organize list` reports it: what is still sorted, and the undo that moves it
    # back.
    folder = crashed_batch(zone, data_dir, {C: "exit-before"})
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    _opened(qtbot, window, "organize")
    assert _banner(window) == [
        "Recovered interrupted organize batches: 1",
        "Batch 1: Failed.",
        f"Still sorted: {folder / MOVED[A]}",
        f"Still sorted: {folder / MOVED[B]}",
        "Undo batch 1 moves them back.",
    ]
    assert window.recovery.offered == frozenset()


def test_a_session_that_finds_unfinished_work_offers_recover(
    qtbot: QtBot, tmp_path: Path, zone: Path, data_dir: Path, dialogs: FakeDialogs
) -> None:
    # [0014.13] [0014.25] Found after the window opened; once recovered, the move runs.
    junk_tree(zone)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    scanned(qtbot, window)
    pending_move_batch(data_dir)
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    assert window.findings.result.text() == (
        "Unfinished work (Organize) comes first: nothing was changed. Use Recover."
    )
    assert _offered(window)
    assert _banner(window) == ["Unfinished work: Organize."]
    _recover(qtbot, window)
    assert window.recovery.offered == frozenset()
    window.findings.move_button.click()
    wait_idle(qtbot, window)
    assert window.findings.result.text().startswith("Moved to the quarantine: 3 files")


def test_a_restore_refuses_while_another_domain_s_work_is_unfinished(
    qtbot: QtBot,
    tmp_path: Path,
    zone: Path,
    data_dir: Path,
    dialogs: FakeDialogs,
    scan: ScanContext,
) -> None:
    # [0014.13]
    quarantined(scan, zone)
    window = _window(qtbot, tmp_path, zone, data_dir, dialogs)
    _opened(qtbot, window, "quarantine")
    pending_move_batch(data_dir)
    window.quarantine.row(1).setCheckState(0, Qt.CheckState.Checked)
    window.quarantine.restore_button.click()
    wait_idle(qtbot, window)
    assert window.quarantine.result.text() == (
        "Unfinished work (Organize) comes first: nothing was changed. Use Recover."
    )
    assert not (zone / "a.bin").exists()
    assert window.recovery.offered == {Domain.ORGANIZE}


# --- in the window's words [0014.25] -------------------------------------------------------------


def test_what_each_domain_s_recovery_closed_in_the_window_s_words(tmp_path: Path) -> None:
    # [0014.25] As `safeclean recover` reports it.
    en = Translator("en")
    paths = (tmp_path / "a", tmp_path / "b")
    found = RecoveryReport(quarantined=paths[:1], lost=paths[1:], warnings=("lost: b",))
    assert quarantine_lines(en, found) == [
        "Recovered an interrupted quarantine operation (2 files).",
        "lost: b",
    ]
    assert quarantine_lines(en, RecoveryReport()) == []
    still = tmp_path / "Images" / "a.jpg"
    batches = (
        RecoveredBatch(1, BatchState.ROLLED_BACK, ()),
        RecoveredBatch(2, BatchState.DONE, (), BatchKind.UNDO, 1),
        RecoveredBatch(3, BatchState.FAILED, (still,)),
        RecoveredBatch(4, BatchState.FAILED, (), BatchKind.UNDO, 3),
    )
    report = organize_recovery.RecoveryReport(batches=batches, warnings=("cannot settle",))
    assert organize_lines(en, report) == [
        "Recovered interrupted organize batches: 4",
        "Batch 1: Rolled back.",
        "Batch 2 (undo of batch 1): Done.",
        "Batch 3: Failed.",
        f"Still sorted: {still}",
        "Undo batch 3 moves them back.",
        "Batch 4 (undo of batch 3): Failed.",
        "Undo batch 3 again to move back the files still sorted.",
        "cannot settle",
    ]
    assert organize_lines(en, organize_recovery.RecoveryReport(warnings=("w",))) == ["w"]
    closed = ChangeRecovery(done=(3,), rolled_back=(1,), failed=(2,))
    assert autostart_lines(en, closed) == [
        "Recovered interrupted autostart changes: 3",
        "Change 1: Rolled back.",
        "Change 2: Failed.",
        "Change 3: Done.",
    ]
    assert autostart_lines(en, ChangeRecovery()) == []
    assert autostart_lines(en, Unclosed("unchecked", "not a regular file")) == [UNCHECKED]
