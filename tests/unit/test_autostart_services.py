"""Reading Windows services that start automatically (step 4, commit 8; decision 0011).

Services live in ``HKLM\\SYSTEM\\CurrentControlSet\\Services``, so nothing is read without
``include_machine`` (item 5). Only Win32 services with ``Start=2`` (automatic) start on their
own: they are listed, enabled; manual and disabled services and drivers are not autostart
entries and are not listed. The command is ``ImagePath`` as written. Anything that cannot be
read or does not parse is skipped with a reason. The registry is a fake; read-only.
"""

import pytest

from fakes import FakeRegistry, RegistryKeys
from safeclean.autostart.models import AutostartListing, AutostartSkipped, Scope, Source
from safeclean.autostart.registry import Hive, Registry, RegValue, ValueKind
from safeclean.autostart.services import SERVICES, read_services

OWN, SHARED, USER_OWN, USER_INSTANCE = 0x10, 0x20, 0x50, 0xD0
AUTO, MANUAL, DISABLED = 2, 3, 4
IMAGE = r'"C:\Program Files\Sync\syncsvc.exe" /service'

Keys = dict[tuple[Hive, str], list[RegValue]]


def dword(name: str, data: int) -> RegValue:
    return RegValue(name, ValueKind.REG_DWORD, data)


def sz(name: str, data: str) -> RegValue:
    return RegValue(name, ValueKind.REG_SZ, data)


def image(data: str = IMAGE, kind: ValueKind = ValueKind.REG_EXPAND_SZ) -> RegValue:
    return RegValue("ImagePath", kind, data)


def valid(kind: int = OWN, start: int = AUTO) -> tuple[RegValue, ...]:
    return dword("Type", kind), dword("Start", start), image()


def service(name: str, kind: int = OWN, start: int = AUTO, *extra: RegValue) -> Keys:
    return key(name, *valid(kind, start), *extra)


def key(name: str, *values: RegValue) -> Keys:
    return {(Hive.HKLM, rf"{SERVICES}\{name}"): list(values)}


def read(keys: RegistryKeys, *, include_machine: bool = True) -> AutostartListing:
    registry: Registry = FakeRegistry(keys)
    return read_services(registry, include_machine=include_machine)


def skip(name: str, detail: str) -> AutostartListing:
    location = rf"HKLM\{SERVICES}\{name}"
    return AutostartListing((), (AutostartSkipped(Source.SERVICE, location, detail),))


# --- items -------------------------------------------------------------------------------------


def test_an_automatic_service_is_an_enabled_system_item() -> None:
    (found,) = read(service("SyncSvc")).items

    assert found.source is Source.SERVICE
    assert found.scope is Scope.SYSTEM
    assert found.name == "SyncSvc"
    assert found.command == IMAGE
    assert found.location == rf"HKLM\{SERVICES}\SyncSvc"
    assert found.enabled is True
    assert found.notes == ()
    assert found.disableable is False


def test_nothing_is_read_without_consent() -> None:
    registry = FakeRegistry(service("SyncSvc"))

    assert read_services(registry, include_machine=False) == AutostartListing((), ())
    assert registry.reads == []


@pytest.mark.parametrize("start", [MANUAL, DISABLED])
def test_manual_and_disabled_services_are_not_listed(start: int) -> None:
    assert read(service("SyncSvc", OWN, start)) == AutostartListing((), ())


@pytest.mark.parametrize("kind", [0x1, 0x2, 0x4, 0x8])
def test_drivers_are_not_listed(kind: int) -> None:
    assert read(service("disk", kind, 0) | service("fs", kind, AUTO)) == AutostartListing((), ())


def test_a_key_without_a_type_is_not_a_service() -> None:
    assert read(key("Leftover", dword("Start", AUTO), image())) == AutostartListing((), ())


@pytest.mark.parametrize(
    ("kind", "notes"),
    [
        (SHARED, ("shared process",)),
        (OWN | 0x100, ()),  # SERVICE_INTERACTIVE_PROCESS changes nothing here
        (USER_OWN, ("per-user service template",)),
        (USER_OWN | SHARED, ("shared process", "per-user service template")),
    ],
)
def test_the_service_type_becomes_notes(kind: int, notes: tuple[str, ...]) -> None:
    (found,) = read(service("SyncSvc", kind)).items

    assert found.notes == notes


def test_per_user_instances_are_not_listed_their_template_is() -> None:
    keys = service("CDPUserSvc", USER_OWN) | service("CDPUserSvc_4a1b2", USER_INSTANCE)

    assert [i.name for i in read(keys).items] == ["CDPUserSvc"]


@pytest.mark.parametrize(("delayed", "notes"), [(1, ("delayed start",)), (0, ())])
def test_a_delayed_start_is_a_note(delayed: int, notes: tuple[str, ...]) -> None:
    (found,) = read(service("SyncSvc", OWN, AUTO, dword("DelayedAutostart", delayed))).items

    assert found.notes == notes


def test_image_path_is_kept_unexpanded() -> None:
    svchost = r"%SystemRoot%\system32\svchost.exe -k netsvcs -p"
    keys = key("Schedule", dword("Type", SHARED), dword("Start", AUTO), image(svchost))

    (found,) = read(keys).items

    assert found.command == svchost


def test_value_names_match_ignoring_case() -> None:
    keys = key("SyncSvc", dword("TYPE", OWN), dword("start", AUTO), sz("imagepath", "x"))

    assert [i.command for i in read(keys).items] == ["x"]


def test_services_are_ordered_by_name_ignoring_case() -> None:
    keys = service("b") | service("C") | service("a")

    assert [i.name for i in read(keys).items] == ["a", "b", "C"]


# --- what is skipped ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "detail"),
    [
        ((dword("Type", OWN), image()), "no Start value"),
        ((dword("Type", OWN), dword("Start", AUTO)), "no ImagePath value"),
        ((sz("Type", "16"), dword("Start", AUTO), image()), "Type is not a DWORD"),
        ((dword("Type", OWN), sz("Start", "2"), image()), "Start is not a DWORD"),
        (valid(OWN, 0), "start type 0 is for drivers only"),
        (valid(OWN, 1), "start type 1 is for drivers only"),
        (valid(OWN, 7), "unknown start type 7"),
        (valid(0x400), "unknown service type 0x400"),
        (valid(OWN | 0x200), "unknown service type 0x210"),
        (
            (dword("Type", OWN), dword("Start", AUTO), image("x", ValueKind.REG_DWORD)),
            "ImagePath is not a string value (REG_DWORD)",
        ),
        ((dword("Type", OWN), dword("Start", AUTO), image("")), "empty command"),
        ((*valid(), sz("DelayedAutostart", "1")), "DelayedAutostart is not a DWORD"),
    ],
)
def test_a_service_that_does_not_parse_is_skipped(
    values: tuple[RegValue, ...], detail: str
) -> None:
    assert read(key("SyncSvc", *values)) == skip("SyncSvc", detail)


def test_a_manual_service_is_not_parsed_further() -> None:
    keys = key("Idle", dword("Type", OWN), dword("Start", MANUAL), image(""))

    assert read(keys) == AutostartListing((), ())


def test_a_service_key_that_cannot_be_read_is_skipped_and_the_others_are_read() -> None:
    keys = service("Locked") | service("SyncSvc")
    registry = FakeRegistry(keys, denied=[(Hive.HKLM, rf"{SERVICES}\Locked")])

    listing = read_services(registry, include_machine=True)

    assert [i.name for i in listing.items] == ["SyncSvc"]
    assert listing.skipped == skip("Locked", "cannot read: access denied").skipped


def test_an_unreadable_services_key_is_one_skip() -> None:
    registry = FakeRegistry(service("SyncSvc"), denied=[(Hive.HKLM, SERVICES)])

    listing = read_services(registry, include_machine=True)

    assert listing == AutostartListing(
        (), (AutostartSkipped(Source.SERVICE, rf"HKLM\{SERVICES}", "cannot read: access denied"),)
    )


def test_a_missing_services_key_gives_an_empty_listing() -> None:
    assert read({}) == AutostartListing((), ())


# --- the digest ----------------------------------------------------------------------------------


def test_the_digest_changes_with_every_value_that_decides_the_item() -> None:
    def digest(*extra: RegValue, kind: int = OWN, path: str = IMAGE) -> str:
        values = (dword("Type", kind), dword("Start", AUTO), image(path), *extra)
        (found,) = read(key("SyncSvc", *values)).items
        return found.digest

    base = digest()
    assert digest() == base
    assert digest(kind=SHARED) != base
    assert digest(path="other.exe") != base
    delayed = digest(dword("DelayedAutostart", 1))
    assert delayed != base
    assert digest(dword("DelayedAutostart", 0)) not in {base, delayed}
    assert digest(sz("DisplayName", "Sync")) == base  # not part of the entry
