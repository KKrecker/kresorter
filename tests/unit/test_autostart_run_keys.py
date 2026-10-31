"""Reading Windows Run and RunOnce values (step 4, commit 5; decision 0011).

``HKCU`` is always read, ``HKLM`` only with ``include_machine``. The state of a Run value comes
from ``Explorer\\StartupApproved\\Run``, as the Task Manager shows it: no flag means enabled, an
unknown flag means an unknown state, and an unknown state is not shown (0011, item 12). RunOnce
values have no such flag and are listed as they are. The registry is a fake: nothing is read
from, or written to, a real one.
"""

import pytest

from fakes import FakeRegistry, RegistryKeys
from safeclean.autostart.models import (
    AutostartItem,
    AutostartListing,
    AutostartSkipped,
    Scope,
    Source,
)
from safeclean.autostart.registry import (
    Hive,
    Registry,
    RegValue,
    ValueKind,
    value_digest,
)
from safeclean.autostart.run_keys import (
    APPROVED,
    APPROVED_32,
    RUN,
    RUN_32,
    RUN_ONCE,
    RUN_ONCE_32,
    read_run_keys,
)

ENABLED = bytes([0x02]) + bytes(11)
DISABLED = bytes([0x03]) + bytes(3) + bytes(range(8))  # flag, padding, FILETIME of the change

def sz(name: str, data: str, kind: ValueKind = ValueKind.REG_SZ) -> RegValue:
    return RegValue(name, kind, data)


def flag(name: str, data: bytes) -> RegValue:
    return RegValue(name, ValueKind.REG_BINARY, data)


def read(keys: RegistryKeys, *, include_machine: bool = False) -> AutostartListing:
    registry: Registry = FakeRegistry(keys)
    return read_run_keys(registry, include_machine=include_machine)


def only(listing: AutostartListing) -> AutostartItem:
    (item,) = listing.items
    assert listing.skipped == ()
    return item


def skip(hive: Hive, key: str, name: str, detail: str) -> AutostartListing:
    location = rf"{hive}\{key}\{name}"
    source = Source.RUN_ONCE_KEY if key in (RUN_ONCE, RUN_ONCE_32) else Source.RUN_KEY
    return AutostartListing(items=(), skipped=(AutostartSkipped(source, location, detail),))


# --- Run ---------------------------------------------------------------------------------------


def test_a_user_run_value_without_a_flag_is_enabled() -> None:
    value = sz("Sync", r'"C:\Program Files\Sync\sync.exe" /tray')

    assert only(read({(Hive.HKCU, RUN): [value]})) == AutostartItem(
        source=Source.RUN_KEY,
        scope=Scope.USER,
        name="Sync",
        command=r'"C:\Program Files\Sync\sync.exe" /tray',
        location=rf"HKCU\{RUN}\Sync",
        enabled=True,
        digest=value_digest(value, None),
    )


@pytest.mark.parametrize(
    ("data", "enabled"),
    [
        (ENABLED, True),
        (bytes([0x06]) + bytes(11), True),
        (DISABLED, False),
        (bytes([0x07]) + bytes(11), False),
    ],
)
def test_startup_approved_decides_the_state(data: bytes, enabled: bool) -> None:
    value, approved = sz("Sync", "sync.exe"), flag("Sync", data)

    found = only(read({(Hive.HKCU, RUN): [value], (Hive.HKCU, APPROVED): [approved]}))

    assert found.enabled is enabled
    assert found.digest == value_digest(value, approved)


def test_a_disabled_value_names_the_key_that_disables_it() -> None:
    keys = {(Hive.HKCU, RUN): [sz("Sync", "x")], (Hive.HKCU, APPROVED): [flag("Sync", DISABLED)]}

    assert only(read(keys)).notes == (rf"disabled in HKCU\{APPROVED}",)


def test_value_names_match_their_flag_case_insensitively() -> None:
    keys = {(Hive.HKCU, RUN): [sz("Sync", "x")], (Hive.HKCU, APPROVED): [flag("SYNC", DISABLED)]}

    assert only(read(keys)).enabled is False


def test_a_flag_without_a_run_value_is_not_an_item() -> None:
    assert read({(Hive.HKCU, APPROVED): [flag("Gone", DISABLED)]}) == AutostartListing((), ())


def test_an_expandable_string_is_kept_unexpanded() -> None:
    value = sz("Tool", r"%LOCALAPPDATA%\Tool\tool.exe", ValueKind.REG_EXPAND_SZ)

    assert only(read({(Hive.HKCU, RUN): [value]})).command == r"%LOCALAPPDATA%\Tool\tool.exe"


def test_the_default_value_is_named_like_regedit_does() -> None:
    found = only(read({(Hive.HKCU, RUN): [sz("", "x.exe")]}))

    assert found.name == "(Default)"
    assert found.location == rf"HKCU\{RUN}\(Default)"


def test_items_are_ordered_by_hive_key_then_name_ignoring_case() -> None:
    keys = {
        (Hive.HKLM, RUN_ONCE_32): [sz("Patch", "p")],
        (Hive.HKLM, RUN_32): [sz("Old", "o")],
        (Hive.HKLM, RUN): [sz("Agent", "a")],
        (Hive.HKCU, RUN_ONCE): [sz("Setup", "s")],
        (Hive.HKCU, RUN): [sz("beta", "b"), sz("Alpha", "a")],
    }

    listing = read(keys, include_machine=True)

    assert [i.location.rpartition("\\")[::2] for i in listing.items] == [
        (rf"HKCU\{RUN}", "Alpha"),
        (rf"HKCU\{RUN}", "beta"),
        (rf"HKCU\{RUN_ONCE}", "Setup"),
        (rf"HKLM\{RUN}", "Agent"),
        (rf"HKLM\{RUN_32}", "Old"),
        (rf"HKLM\{RUN_ONCE_32}", "Patch"),
    ]


# --- RunOnce -----------------------------------------------------------------------------------


def test_run_once_values_are_listed_as_they_are_without_a_flag() -> None:
    value = sz("Setup", "setup.exe /finish")
    keys = {(Hive.HKCU, RUN_ONCE): [value], (Hive.HKCU, APPROVED): [flag("Setup", DISABLED)]}

    assert only(read(keys)) == AutostartItem(
        source=Source.RUN_ONCE_KEY,
        scope=Scope.USER,
        name="Setup",
        command="setup.exe /finish",
        location=rf"HKCU\{RUN_ONCE}\Setup",
        enabled=True,
        digest=value_digest(value, None),
        notes=("runs once at the next logon",),
    )


# --- HKLM is opt-in ----------------------------------------------------------------------------


def test_the_machine_hive_is_not_even_read_without_consent() -> None:
    registry = FakeRegistry({(Hive.HKLM, RUN): [sz("Agent", "agent.exe")]})

    listing = read_run_keys(registry, include_machine=False)

    assert listing == AutostartListing((), ())
    assert {hive for hive, _ in registry.reads} == {Hive.HKCU}


def test_machine_values_are_system_scope_and_use_their_own_flags() -> None:
    keys = {
        (Hive.HKLM, RUN): [sz("Agent", "agent.exe")],
        (Hive.HKLM, APPROVED): [flag("Agent", DISABLED)],
        (Hive.HKCU, APPROVED): [flag("Agent", ENABLED)],
    }

    found = only(read(keys, include_machine=True))

    assert found.scope is Scope.SYSTEM
    assert found.enabled is False
    assert found.disableable is False


# --- the 32-bit view of HKLM is read apart, with its own flags (0011, item 20) -----------------


def test_a_32_bit_value_is_a_machine_run_value_of_its_own() -> None:
    value = sz("Old", r"C:\Program Files (x86)\Old\old.exe")

    assert only(read({(Hive.HKLM, RUN_32): [value]}, include_machine=True)) == AutostartItem(
        source=Source.RUN_KEY,
        scope=Scope.SYSTEM,
        name="Old",
        command=r"C:\Program Files (x86)\Old\old.exe",
        location=rf"HKLM\{RUN_32}\Old",
        enabled=True,
        digest=value_digest(value, None),
        notes=("32-bit view",),
    )


def test_the_32_bit_view_uses_run32_flags_and_never_the_64_bit_ones() -> None:
    keys = {
        (Hive.HKLM, RUN): [sz("Agent", "a")],
        (Hive.HKLM, RUN_32): [sz("Agent", "a32")],
        (Hive.HKLM, APPROVED): [flag("Agent", ENABLED)],
        (Hive.HKLM, APPROVED_32): [flag("Agent", DISABLED)],
    }

    listing = read(keys, include_machine=True)

    assert [(i.command, i.enabled, i.notes) for i in listing.items] == [
        ("a", True, ()),
        ("a32", False, ("32-bit view", rf"disabled in HKLM\{APPROVED_32}")),
    ]


def test_32_bit_run_once_values_carry_both_notes() -> None:
    keys = {(Hive.HKLM, RUN_ONCE_32): [sz("Patch", "patch.exe")]}

    found = only(read(keys, include_machine=True))

    assert found.source is Source.RUN_ONCE_KEY
    assert found.notes == ("32-bit view", "runs once at the next logon")


def test_the_32_bit_view_is_machine_only_and_needs_consent() -> None:
    keys = {(Hive.HKLM, RUN_32): [sz("Old", "old.exe")]}
    with_consent, without = FakeRegistry(keys), FakeRegistry(keys)

    read_run_keys(with_consent, include_machine=True)

    assert (Hive.HKLM, RUN_32) in with_consent.reads
    assert (Hive.HKCU, RUN_32) not in with_consent.reads
    assert read_run_keys(without, include_machine=False) == AutostartListing((), ())


def test_an_unreadable_run32_flag_key_is_one_skip_of_its_own() -> None:
    registry = FakeRegistry(
        {(Hive.HKLM, RUN): [sz("Agent", "a")], (Hive.HKLM, RUN_32): [sz("Old", "o")]},
        denied=[(Hive.HKLM, APPROVED_32)],
    )

    listing = read_run_keys(registry, include_machine=True)

    assert [i.name for i in listing.items] == ["Agent"]
    assert listing.skipped == (
        AutostartSkipped(Source.RUN_KEY, rf"HKLM\{APPROVED_32}", "cannot read: access denied"),
    )


# --- what cannot be read is skipped, never fatal -----------------------------------------------


@pytest.mark.parametrize(
    ("value", "detail"),
    [
        (RegValue("Sync", ValueKind.REG_DWORD, 1), "not a string value (REG_DWORD)"),
        (RegValue("Sync", ValueKind.REG_MULTI_SZ, ["a", "b"]), "not a string value (REG_MULTI_SZ)"),
        (RegValue("Sync", 99, "x"), "not a string value (type 99)"),
        (sz("Sync", ""), "empty command"),
    ],
)
def test_a_value_that_is_not_a_command_is_skipped(value: RegValue, detail: str) -> None:
    assert read({(Hive.HKCU, RUN): [value]}) == skip(Hive.HKCU, RUN, "Sync", detail)


@pytest.mark.parametrize(
    ("approved", "detail"),
    [
        (flag("Sync", bytes([0x05]) + bytes(11)), "unknown StartupApproved state 0x05"),
        (flag("Sync", b""), "unknown StartupApproved state (empty)"),
        (RegValue("Sync", ValueKind.REG_DWORD, 2), "StartupApproved value is not binary"),
    ],
)
def test_an_unknown_state_is_skipped_not_shown(approved: RegValue, detail: str) -> None:
    keys = {(Hive.HKCU, RUN): [sz("Sync", "sync.exe")], (Hive.HKCU, APPROVED): [approved]}

    assert read(keys) == skip(Hive.HKCU, RUN, "Sync", detail)


def test_an_unreadable_key_is_skipped_and_the_others_are_read() -> None:
    registry = FakeRegistry(
        {(Hive.HKCU, RUN_ONCE): [sz("Setup", "setup.exe")]}, denied=[(Hive.HKCU, RUN)]
    )

    listing = read_run_keys(registry, include_machine=False)

    assert [i.name for i in listing.items] == ["Setup"]
    assert listing.skipped == (
        AutostartSkipped(Source.RUN_KEY, rf"HKCU\{RUN}", "cannot read: access denied"),
    )


def test_an_unreadable_flag_key_makes_every_run_state_unknown() -> None:
    registry = FakeRegistry(
        {(Hive.HKCU, RUN): [sz("Sync", "sync.exe")]}, denied=[(Hive.HKCU, APPROVED)]
    )

    listing = read_run_keys(registry, include_machine=False)

    assert listing.items == ()
    assert listing.skipped == (
        AutostartSkipped(Source.RUN_KEY, rf"HKCU\{APPROVED}", "cannot read: access denied"),
    )


def test_missing_keys_give_an_empty_listing() -> None:
    assert read({}, include_machine=True) == AutostartListing((), ())


# --- the digest ----------------------------------------------------------------------------------


def test_the_digest_changes_with_name_kind_data_and_flag() -> None:
    value = sz("Sync", "a")
    base = value_digest(value, None)

    assert value_digest(sz("Sync", "a"), None) == base
    assert value_digest(sz("Other", "a"), None) != base
    assert value_digest(sz("Sync", "a", ValueKind.REG_EXPAND_SZ), None) != base
    assert value_digest(sz("Sync", "b"), None) != base
    enabled = value_digest(value, flag("Sync", ENABLED))
    assert enabled != base
    assert value_digest(value, flag("Sync", DISABLED)) != enabled


def test_the_digest_keeps_field_boundaries() -> None:
    assert value_digest(sz("ab", "c"), None) != value_digest(sz("a", "bc"), None)


def test_the_digest_tells_every_data_type_apart() -> None:
    values = [
        RegValue("x", ValueKind.REG_SZ, "1"),
        RegValue("x", ValueKind.REG_DWORD, 1),
        RegValue("x", ValueKind.REG_BINARY, b"1"),
        RegValue("x", ValueKind.REG_MULTI_SZ, ["1"]),
        RegValue("x", ValueKind.REG_MULTI_SZ, ["a", "b"]),
        RegValue("x", ValueKind.REG_MULTI_SZ, ["ab"]),
        RegValue("x", ValueKind.REG_NONE, None),
    ]

    assert len({value_digest(v) for v in values}) == len(values)
    assert value_digest(values[0], None) != value_digest(None, values[0])
