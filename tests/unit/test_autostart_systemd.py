"""Reading enabled systemd user units (step 4, commit 4; decision 0011, items 1, 3, 9).

An enabled unit is a link in ``$XDG_CONFIG_HOME/systemd/user/<target>.wants/``. Each link is
one item: ``location`` is the link, the target it was enabled for is a note, ``command`` is the
``ExecStart`` of the unit file the link leads to, kept as written. A unit masked in the same
directory (a link to ``/dev/null``) is listed as disabled. Read-only, never fatal: anything
that cannot be read is skipped with a reason.
"""

import os
from pathlib import Path

import pytest

from kresorter.autostart.entries import MAX_ENTRY_BYTES
from kresorter.autostart.models import (
    AutostartItem,
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
    entry_digest,
)
from kresorter.autostart.systemd import read_systemd_user, systemd_user_dir

SYNC = "[Unit]\nDescription=Sync\n\n[Service]\nExecStart=/usr/bin/sync --serve\n"


@pytest.fixture
def units(tmp_path: Path) -> Path:
    return tmp_path / "home" / ".config" / "systemd" / "user"


@pytest.fixture
def vendor(tmp_path: Path) -> Path:
    return tmp_path / "usr" / "lib" / "systemd" / "user"


def unit(directory: Path, name: str, text: str = SYNC) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(text.encode())
    return path


def enable(units: Path, target: str, name: str, unit_file: Path | str) -> Path:
    wants = units / f"{target}.wants"
    wants.mkdir(parents=True, exist_ok=True)
    link = wants / name
    link.symlink_to(unit_file)
    return link


def digest_of(link: Path) -> str:
    return entry_digest(os.fsencode(link.readlink()) + b"\0" + link.read_bytes())


def only(listing: AutostartListing) -> AutostartItem:
    (item,) = listing.items
    assert listing.skipped == ()
    return item


def skipped(location: Path, detail: str) -> AutostartListing:
    return AutostartListing(
        items=(), skipped=(AutostartSkipped(Source.SYSTEMD_USER, str(location), detail),)
    )


# --- enabled units -----------------------------------------------------------------------------


def test_an_enabled_service(units: Path, vendor: Path) -> None:
    link = enable(units, "default.target", "sync.service", unit(vendor, "sync.service"))

    assert only(read_systemd_user(units)) == AutostartItem(
        source=Source.SYSTEMD_USER,
        scope=Scope.USER,
        name="sync.service",
        command="/usr/bin/sync --serve",
        location=str(link),
        enabled=True,
        digest=digest_of(link),
        notes=("WantedBy=default.target",),
    )


def test_a_relative_link_is_resolved_from_its_directory(units: Path) -> None:
    unit(units, "sync.service")
    link = enable(units, "default.target", "sync.service", "../sync.service")

    found = only(read_systemd_user(units))

    assert found.command == "/usr/bin/sync --serve"
    assert found.digest == digest_of(link)


def test_the_digest_covers_the_link_target_too(tmp_path: Path, vendor: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    enable(first, "default.target", "sync.service", unit(vendor, "sync.service"))
    enable(second, "default.target", "sync.service", unit(vendor / "copy", "sync.service"))

    assert only(read_systemd_user(first)).digest != only(read_systemd_user(second)).digest


def test_a_unit_file_copied_into_wants_is_read_as_it_is(units: Path) -> None:
    copy = unit(units / "default.target.wants", "sync.service")

    found = only(read_systemd_user(units))

    assert found.location == str(copy)
    assert found.digest == entry_digest(b"\0" + copy.read_bytes())


def test_one_item_per_link_ordered_by_name_then_location(units: Path, vendor: Path) -> None:
    sync = unit(vendor, "sync.service")
    enable(units, "graphical-session.target", "sync.service", sync)
    enable(units, "default.target", "sync.service", sync)
    enable(units, "default.target", "agent.service", unit(vendor, "agent.service"))

    listing = read_systemd_user(units)

    assert [(i.name, i.notes) for i in listing.items] == [
        ("agent.service", ("WantedBy=default.target",)),
        ("sync.service", ("WantedBy=default.target",)),
        ("sync.service", ("WantedBy=graphical-session.target",)),
    ]


def test_a_template_instance_keeps_its_specifiers(units: Path, vendor: Path) -> None:
    template = unit(vendor, "mount@.service", "[Service]\nExecStart=/usr/bin/mnt %i\n")
    enable(units, "default.target", "mount@data.service", template)

    found = only(read_systemd_user(units))

    assert found.name == "mount@data.service"
    assert found.command == "/usr/bin/mnt %i"


def test_a_masked_unit_is_listed_as_disabled(units: Path, vendor: Path) -> None:
    enable(units, "default.target", "sync.service", unit(vendor, "sync.service"))
    (units / "sync.service").symlink_to(os.devnull)

    found = only(read_systemd_user(units))

    assert found.enabled is False
    assert found.notes == ("WantedBy=default.target", "masked")


def test_a_unit_that_is_not_a_service_names_its_unit_file(units: Path, vendor: Path) -> None:
    timer = unit(vendor, "backup.timer", "[Timer]\nOnCalendar=daily\n")
    enable(units, "timers.target", "backup.timer", timer)

    found = only(read_systemd_user(units))

    assert found.command == str(timer)
    assert found.notes == ("WantedBy=timers.target", "not a service: timer")


def test_missing_directory_gives_an_empty_listing(units: Path) -> None:
    assert read_systemd_user(units) == AutostartListing(items=(), skipped=())


def test_only_wants_directories_and_unit_names_count(units: Path, vendor: Path) -> None:
    sync = unit(vendor, "sync.service")
    unit(units, "sync.service")
    unit(units / "sync.service.d", "override.conf", "[Service]\nExecStart=/x\n")
    enable(units, "default.target", "README", sync)
    requires = units / "default.target.requires"
    requires.mkdir()
    (requires / "sync.service").symlink_to(sync)

    assert read_systemd_user(units) == AutostartListing(items=(), skipped=())


# --- ExecStart -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("service", "command"),
    [
        ("[Service]\nExecStart=/bin/a\nExecStart=/bin/b\n", "/bin/a; /bin/b"),
        ("[Service]\nExecStart=/bin/a\nExecStart=\nExecStart=/bin/b\n", "/bin/b"),
        ("[Service]\nExecStart=/bin/a \\\n  --flag\n", "/bin/a --flag"),
        ("# c\n; c\n[Unit]\nExecStart=/no\n[Service]\nExecStart = -/bin/a\n", "-/bin/a"),
        ("[Service]\nExecStart=/bin/a\n[Install]\nExecStart=/no\n", "/bin/a"),
    ],
)
def test_exec_start_as_written(units: Path, vendor: Path, service: str, command: str) -> None:
    enable(units, "default.target", "a.service", unit(vendor, "a.service", service))

    assert only(read_systemd_user(units)).command == command


# --- broken units are skipped, never fatal -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "detail"),
    [
        ("[Unit]\nDescription=x\n", "no ExecStart in [Service]"),
        ("[Service]\nExecStart=\n", "no ExecStart in [Service]"),
        ("[Service]\nExecStart=/bin/a\njunk\n", "malformed line 3"),
        ("ExecStart=/bin/a\n", "malformed line 1"),
    ],
)
def test_a_broken_service_is_skipped(units: Path, vendor: Path, text: str, detail: str) -> None:
    link = enable(units, "default.target", "a.service", unit(vendor, "a.service", text))

    assert read_systemd_user(units) == skipped(link, detail)


def test_a_dangling_link_is_skipped(units: Path, vendor: Path) -> None:
    link = enable(units, "default.target", "gone.service", vendor / "gone.service")

    (skip,) = read_systemd_user(units).skipped

    assert skip.location == str(link)
    assert skip.detail.startswith("cannot read:")


def test_a_unit_file_that_is_not_utf8_is_skipped(units: Path, vendor: Path) -> None:
    vendor.mkdir(parents=True)
    (vendor / "a.service").write_bytes(b"[Service]\nExecStart=/bin/\xe9\n")
    link = enable(units, "default.target", "a.service", vendor / "a.service")

    assert read_systemd_user(units) == skipped(link, "not UTF-8")


def test_an_oversized_unit_file_is_skipped_unread(units: Path, vendor: Path) -> None:
    big = unit(vendor, "a.service", SYNC + "#" * MAX_ENTRY_BYTES)
    link = enable(units, "default.target", "a.service", big)

    assert read_systemd_user(units) == skipped(link, f"larger than {MAX_ENTRY_BYTES} bytes")


def test_a_link_to_something_that_is_not_a_regular_file_is_skipped(
    units: Path, vendor: Path
) -> None:
    vendor.mkdir(parents=True)
    os.mkfifo(vendor / "pipe.service")  # opening it would block: never opened
    link = enable(units, "default.target", "pipe.service", vendor / "pipe.service")

    assert read_systemd_user(units) == skipped(link, "not a regular file")


def test_reading_never_writes(tmp_path: Path, units: Path, vendor: Path) -> None:
    enable(units, "default.target", "sync.service", unit(vendor, "sync.service"))
    enable(units, "default.target", "bad.service", unit(vendor, "bad.service", "[Unit]\n"))
    before = sorted((p, p.read_bytes(), p.stat().st_mtime_ns) for p in vendor.iterdir())

    read_systemd_user(units)

    assert sorted((p, p.read_bytes(), p.stat().st_mtime_ns) for p in vendor.iterdir()) == before
    assert sorted(p.name for p in units.iterdir()) == ["default.target.wants"]


# --- where the directory is --------------------------------------------------------------------


def test_default_directory(tmp_path: Path) -> None:
    assert systemd_user_dir({}, tmp_path) == tmp_path / ".config" / "systemd" / "user"


def test_directory_from_xdg_config_home(tmp_path: Path) -> None:
    assert systemd_user_dir({"XDG_CONFIG_HOME": "/cfg"}, tmp_path) == Path("/cfg/systemd/user")


def test_a_relative_xdg_config_home_is_ignored(tmp_path: Path) -> None:
    expected = tmp_path / ".config" / "systemd" / "user"

    assert systemd_user_dir({"XDG_CONFIG_HOME": "cfg"}, tmp_path) == expected
