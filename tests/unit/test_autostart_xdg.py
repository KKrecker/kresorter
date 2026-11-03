"""Reading XDG autostart entries (step 4, commit 3; decision 0011, items 1, 3, 6, 7).

A user entry (``$XDG_CONFIG_HOME/autostart``) replaces the system entry of the same file name
(first directory of ``$XDG_CONFIG_DIRS`` wins); one item per name shows the effective state,
with the replaced system file in ``shadows``. ``Hidden=true`` and
``X-GNOME-Autostart-enabled=false`` disable; ``OnlyShowIn``/``NotShowIn`` are reported as notes,
never evaluated. A file that cannot be read is skipped with a reason. Reading never writes.
"""

import os
from pathlib import Path

import pytest

from kresorter.autostart.models import (
    AutostartItem,
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
    entry_digest,
)
from kresorter.autostart.xdg import MAX_ENTRY_BYTES, autostart_dirs, read_xdg

APP = "[Desktop Entry]\nType=Application\nName=App\nExec=/usr/bin/app --tray\n"


def desktop(directory: Path, name: str, text: str = APP) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.desktop"
    path.write_bytes(text.encode())
    return path


@pytest.fixture
def user(tmp_path: Path) -> Path:
    return tmp_path / "home" / ".config" / "autostart"


@pytest.fixture
def system(tmp_path: Path) -> Path:
    return tmp_path / "etc" / "xdg" / "autostart"


def read(user: Path, *system: Path) -> AutostartListing:
    return read_xdg(user, system)


def state(root: Path) -> list[tuple[Path, bytes, int]]:
    return sorted((p, p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file())


def only(listing: AutostartListing) -> AutostartItem:
    (item,) = listing.items
    assert listing.skipped == ()
    return item


# --- one entry ---------------------------------------------------------------------------------


def test_a_user_entry(user: Path, system: Path) -> None:
    path = desktop(user, "app")

    assert only(read(user, system)) == AutostartItem(
        source=Source.XDG_AUTOSTART,
        scope=Scope.USER,
        name="app",
        command="/usr/bin/app --tray",
        location=str(path),
        enabled=True,
        digest=entry_digest(path.read_bytes()),
    )


def test_a_system_entry(user: Path, system: Path) -> None:
    path = desktop(system, "app")

    found = only(read(user, system))

    assert found.scope is Scope.SYSTEM
    assert found.location == str(path)
    assert found.shadows is None


def test_items_are_ordered_by_name(user: Path, system: Path) -> None:
    for name in ["zeta", "alpha"]:
        desktop(user, name)
    desktop(system, "mid")

    assert [i.name for i in read(user, system).items] == ["alpha", "mid", "zeta"]


def test_missing_directories_give_an_empty_listing(user: Path, system: Path) -> None:
    assert read(user, system) == AutostartListing(items=(), skipped=())


def not_a_directory(path: Path) -> Path:
    """A directory path that exists but cannot be listed (``NotADirectoryError``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def unreadable(path: Path) -> AutostartSkipped:
    return AutostartSkipped(Source.XDG_AUTOSTART, str(path), "cannot read: Not a directory")


def test_a_user_directory_that_cannot_be_listed_hides_every_entry(user: Path, system: Path) -> None:
    desktop(system, "app")  # a user stub that could not be seen may hide it

    assert read(not_a_directory(user), system) == AutostartListing((), (unreadable(user),))


def test_entries_above_an_unreadable_system_directory_are_still_shown(
    tmp_path: Path, user: Path
) -> None:
    first, broken, last = (tmp_path / d / "autostart" for d in ("a", "b", "c"))
    desktop(first, "kept")
    desktop(last, "kept")
    desktop(last, "below")  # an entry of the same name in `broken` could replace it
    desktop(user, "own")  # it could shadow an entry in `broken`: `shadows` is unknown
    desktop(user, "over")
    over = desktop(first, "over")

    listing = read(user, first, not_a_directory(broken), last)

    assert [(i.name, i.location) for i in listing.items] == [
        ("kept", str(first / "kept.desktop")),
        ("over", str(user / "over.desktop")),
    ]
    assert listing.items[1].shadows == str(over)
    assert listing.skipped == (unreadable(broken),)


def test_an_unreadable_directory_is_reported_before_the_entries(
    tmp_path: Path, user: Path, system: Path
) -> None:
    desktop(user, "broken", "[Desktop Entry]\nType=Application\n")
    desktop(system, "broken")
    later = not_a_directory(tmp_path / "later" / "autostart")

    assert read(user, system, later).skipped == (
        unreadable(later),
        AutostartSkipped(Source.XDG_AUTOSTART, str(user / "broken.desktop"), "no Exec key"),
    )


# --- overrides ---------------------------------------------------------------------------------


def test_a_user_entry_replaces_the_system_entry_of_the_same_name(user: Path, system: Path) -> None:
    shadowed = desktop(system, "app")
    path = desktop(user, "app", APP.replace("--tray", "--quiet"))

    found = only(read(user, system))

    assert found.scope is Scope.USER
    assert found.location == str(path)
    assert found.shadows == str(shadowed)
    assert found.command == "/usr/bin/app --quiet"
    assert found.digest == entry_digest(path.read_bytes())


def test_a_hidden_stub_shows_the_system_entry_as_disabled(user: Path, system: Path) -> None:
    shadowed = desktop(system, "app")
    stub = desktop(user, "app", "[Desktop Entry]\nHidden=true\n")

    found = only(read(user, system))

    assert found.enabled is False
    assert found.location == str(stub)
    assert found.shadows == str(shadowed)
    assert found.command == "/usr/bin/app --tray"  # what the stub keeps from starting


def test_a_hidden_stub_without_a_system_entry_is_skipped(user: Path, system: Path) -> None:
    stub = desktop(user, "app", "[Desktop Entry]\nHidden=true\n")

    assert read(user, system) == AutostartListing(
        items=(),
        skipped=(AutostartSkipped(Source.XDG_AUTOSTART, str(stub), "Hidden=true hides no entry"),),
    )


def test_a_hidden_stub_over_a_broken_system_entry_is_skipped(user: Path, system: Path) -> None:
    desktop(system, "app", "[Desktop Entry]\nType=Application\n")
    stub = desktop(user, "app", "[Desktop Entry]\nHidden=true\n")

    listing = read(user, system)

    assert listing.items == ()
    assert [s.location for s in listing.skipped] == [str(stub)]


def test_a_broken_user_entry_hides_the_system_entry_too(user: Path, system: Path) -> None:
    desktop(system, "app")
    broken = desktop(user, "app", "[Desktop Entry]\nType=Application\n")

    listing = read(user, system)

    assert listing.items == ()
    assert listing.skipped == (AutostartSkipped(Source.XDG_AUTOSTART, str(broken), "no Exec key"),)


def test_the_first_system_directory_wins(tmp_path: Path, user: Path) -> None:
    first, second = tmp_path / "a" / "autostart", tmp_path / "b" / "autostart"
    winner = desktop(first, "app")
    desktop(second, "app", APP.replace("--tray", "--other"))

    found = only(read(user, first, second))

    assert found.location == str(winner)
    assert found.shadows is None


# --- effective state ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("extra", "enabled"),
    [
        ("Hidden=false\n", True),
        ("Hidden=true\n", False),
        ("X-GNOME-Autostart-enabled=true\n", True),
        ("X-GNOME-Autostart-enabled=false\n", False),
        ("Hidden=false\nX-GNOME-Autostart-enabled=false\n", False),
    ],
)
def test_hidden_and_gnome_enabled_decide_the_state(
    user: Path, system: Path, extra: str, enabled: bool
) -> None:
    desktop(system, "app", APP + extra)

    assert only(read(user, system)).enabled is enabled


def test_show_in_lists_are_notes_and_never_change_the_state(user: Path, system: Path) -> None:
    desktop(system, "app", APP + "OnlyShowIn=GNOME;KDE;\nNotShowIn=XFCE;\n")

    found = only(read(user, system))

    assert found.enabled is True
    assert found.notes == ("OnlyShowIn=GNOME;KDE;", "NotShowIn=XFCE;")


def test_an_entry_without_show_in_lists_has_no_notes(user: Path, system: Path) -> None:
    desktop(system, "app")

    assert only(read(user, system)).notes == ()


def test_comments_other_groups_and_localized_keys_are_accepted(user: Path, system: Path) -> None:
    text = (
        "# generated\n\n[Desktop Entry]\nType=Application\nName=App\nName[de]=Anwendung\n"
        "Exec = /usr/bin/app\n# trailing comment\n\n[Desktop Action quit]\nExec=/usr/bin/x\n"
    )
    desktop(system, "app", text)

    assert only(read(user, system)).command == "/usr/bin/app"


def test_a_symlinked_entry_is_read_through_the_link(tmp_path: Path, user: Path) -> None:
    target = desktop(tmp_path / "share" / "applications", "app")
    user.mkdir(parents=True)
    link = user / "app.desktop"
    link.symlink_to(target)

    found = only(read(user))

    assert found.location == str(link)
    assert found.digest == entry_digest(target.read_bytes())


def test_files_without_the_desktop_suffix_are_ignored(user: Path, system: Path) -> None:
    user.mkdir(parents=True)
    (user / "notes.txt").write_text("not an entry")
    (user / "app.desktop~").write_text(APP)

    assert read(user, system) == AutostartListing(items=(), skipped=())


# --- broken entries are skipped, never fatal ---------------------------------------------------


@pytest.mark.parametrize(
    ("text", "detail"),
    [
        ("Type=Application\nExec=app\n", "no [Desktop Entry] group"),
        ("[Other]\nExec=app\n", "no [Desktop Entry] group"),
        ("# only a comment\n", "no [Desktop Entry] group"),
        ("[Desktop Entry]\nType=Application\n", "no Exec key"),
        ("[Desktop Entry]\nType=Application\nExec=\n", "no Exec key"),
        ("[Desktop Entry]\nType=Application\nExec=app\njunk\n", "malformed line 4"),
        ("[Desktop Entry]\nExec=a\nExec=b\nType=Application\n", "duplicate key Exec"),
        ("[Desktop Entry]\nType=Application\nExec=app\nHidden=yes\n", "Hidden is not a boolean"),
        ("[Desktop Entry]\nType=Link\nURL=http://x\n", "Type is Link, not Application"),
        ("[Desktop Entry]\nExec=app\n", "no Type key"),
    ],
)
def test_a_broken_entry_is_skipped_with_its_reason(
    user: Path, system: Path, text: str, detail: str
) -> None:
    path = desktop(system, "app", text)

    assert read(user, system) == AutostartListing(
        items=(), skipped=(AutostartSkipped(Source.XDG_AUTOSTART, str(path), detail),)
    )


def test_a_file_that_is_not_utf8_is_skipped(user: Path, system: Path) -> None:
    system.mkdir(parents=True)
    path = system / "app.desktop"
    path.write_bytes(APP.encode() + b"Name[fr]=\xe9\n")

    assert read(user, system).skipped == (
        AutostartSkipped(Source.XDG_AUTOSTART, str(path), "not UTF-8"),
    )


def test_an_oversized_file_is_skipped_unread(user: Path, system: Path) -> None:
    path = desktop(system, "app", APP + "#" * MAX_ENTRY_BYTES)

    assert read(user, system).skipped == (
        AutostartSkipped(Source.XDG_AUTOSTART, str(path), f"larger than {MAX_ENTRY_BYTES} bytes"),
    )


def test_something_that_is_not_a_regular_file_is_skipped(user: Path, system: Path) -> None:
    (system / "dir.desktop").mkdir(parents=True)
    os.mkfifo(system / "pipe.desktop")  # opening it would block: never opened

    assert read(user, system).skipped == (
        AutostartSkipped(Source.XDG_AUTOSTART, str(system / "dir.desktop"), "not a regular file"),
        AutostartSkipped(Source.XDG_AUTOSTART, str(system / "pipe.desktop"), "not a regular file"),
    )


def test_a_dangling_symlink_is_skipped(user: Path) -> None:
    user.mkdir(parents=True)
    link = user / "app.desktop"
    link.symlink_to(user / "missing.desktop")

    (skipped,) = read(user).skipped

    assert skipped.location == str(link)
    assert skipped.detail.startswith("cannot read:")


def test_reading_never_writes(tmp_path: Path, user: Path, system: Path) -> None:
    desktop(user, "app", "[Desktop Entry]\nHidden=true\n")
    desktop(system, "app")
    desktop(system, "broken", "[Desktop Entry]\n")
    before = state(tmp_path)

    read(user, system)

    assert state(tmp_path) == before


# --- where the directories are -----------------------------------------------------------------


def test_default_directories(tmp_path: Path) -> None:
    home = tmp_path / "me"

    assert autostart_dirs({}, home) == (
        home / ".config" / "autostart",
        (Path("/etc/xdg/autostart"),),
    )


def test_directories_from_the_environment(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": "/cfg", "XDG_CONFIG_DIRS": "/one:/two"}

    assert autostart_dirs(env, tmp_path) == (
        Path("/cfg/autostart"),
        (Path("/one/autostart"), Path("/two/autostart")),
    )


def test_relative_and_empty_environment_values_are_ignored(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": "cfg", "XDG_CONFIG_DIRS": "rel::/abs:"}

    assert autostart_dirs(env, tmp_path) == (
        tmp_path / ".config" / "autostart",
        (Path("/abs/autostart"),),
    )


def test_no_usable_config_dirs_fall_back_to_etc_xdg(tmp_path: Path) -> None:
    assert autostart_dirs({"XDG_CONFIG_DIRS": "rel:"}, tmp_path)[1] == (Path("/etc/xdg/autostart"),)
