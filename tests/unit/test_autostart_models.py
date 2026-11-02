"""Autostart items: one entry from one source, with its effective state (decision 0011).

``scope`` says where the entry lives; ``digest`` fingerprints the raw entry as read, so an
action can refuse an entry that changed since it was listed. ``shadows`` exists only for an
XDG entry in the user scope that replaces a system file of the same name. Only XDG entries and
``HKCU`` Run values (not RunOnce) can be disabled in step 4.
"""

import dataclasses
from typing import Any

import pytest

from safeclean.autostart.models import (
    AutostartItem,
    AutostartSkipped,
    Scope,
    Source,
    entry_digest,
)

USER_FILE = "/home/me/.config/autostart/app.desktop"
SYSTEM_FILE = "/etc/xdg/autostart/app.desktop"
RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"


BASE = AutostartItem(
    source=Source.XDG_AUTOSTART,
    scope=Scope.USER,
    name="app",
    command="/usr/bin/app --tray",
    location=USER_FILE,
    enabled=True,
    digest=entry_digest(b"[Desktop Entry]\nExec=/usr/bin/app --tray\n"),
)


def item(**changes: Any) -> AutostartItem:
    return dataclasses.replace(BASE, **changes)


def test_sources_and_scopes_are_pinned() -> None:
    assert [str(s) for s in Source] == [
        "xdg_autostart",
        "systemd_user",
        "run_key",
        "run_once_key",
        "startup_folder",
        "service",
        "scheduled_task",
        "launch_agent",
    ]
    assert [str(s) for s in Scope] == ["user", "system"]


def test_an_item_is_immutable() -> None:
    name = "enabled"  # set by name: the type checker knows it is frozen, the test checks it is
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(item(), name, False)


def test_an_item_shadows_nothing_by_default() -> None:
    assert item().shadows is None


def test_a_user_xdg_entry_can_shadow_a_system_file() -> None:
    stub = item(enabled=False, shadows=SYSTEM_FILE)

    assert stub.location == USER_FILE
    assert stub.shadows == SYSTEM_FILE
    assert stub.enabled is False


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": Scope.SYSTEM, "location": SYSTEM_FILE},
        {"source": Source.RUN_KEY, "location": RUN_KEY},
    ],
)
def test_only_a_user_xdg_entry_may_shadow(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="shadows"):
        item(shadows=SYSTEM_FILE, **changes)


@pytest.mark.parametrize(
    ("source", "scope", "disableable"),
    [
        (Source.XDG_AUTOSTART, Scope.USER, True),
        (Source.XDG_AUTOSTART, Scope.SYSTEM, True),
        (Source.RUN_KEY, Scope.USER, True),
        (Source.RUN_KEY, Scope.SYSTEM, False),
        (Source.RUN_ONCE_KEY, Scope.USER, False),
        (Source.SYSTEMD_USER, Scope.USER, False),
        (Source.STARTUP_FOLDER, Scope.USER, False),
        (Source.SERVICE, Scope.SYSTEM, False),
        (Source.SCHEDULED_TASK, Scope.SYSTEM, False),
        (Source.LAUNCH_AGENT, Scope.USER, False),
    ],
)
def test_only_xdg_entries_and_user_run_values_can_be_disabled(
    source: Source, scope: Scope, disableable: bool
) -> None:
    assert item(source=source, scope=scope).disableable is disableable


@pytest.mark.parametrize("field", ["name", "command", "location"])
def test_required_text_must_not_be_empty(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        item(**{field: ""})


@pytest.mark.parametrize("digest", ["", "abc", "g" * 32, "A" * 32])
def test_a_digest_must_come_from_entry_digest(digest: str) -> None:
    with pytest.raises(ValueError, match="digest"):
        item(digest=digest)


def test_entry_digest_is_a_stable_fingerprint_of_the_raw_entry() -> None:
    first = entry_digest(b"Exec=app\n")

    assert first == entry_digest(b"Exec=app\n")
    assert first != entry_digest(b"Exec=app --tray\n")
    assert len(first) == 32
    assert set(first) <= set("0123456789abcdef")


def test_a_skipped_entry_says_where_and_why() -> None:
    skipped = AutostartSkipped(Source.XDG_AUTOSTART, USER_FILE, "no Exec key")

    assert skipped.source is Source.XDG_AUTOSTART
    assert skipped.location == USER_FILE
    assert skipped.detail == "no Exec key"
