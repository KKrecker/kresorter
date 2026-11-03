"""The adapter from the ``Registry`` protocol to the real ``winreg`` (step 4, commit 6; 0011).

``winreg`` exists only on Windows, so it is imported on first use and the tests drive the
adapter with a stand-in module, like ``MsvcrtBackend`` (decision 0009). Keys are opened for
reading in the 64-bit view, so an explicit ``WOW6432Node`` path means exactly that key. A
missing key reads as ``None``; any other failure is a ``RegistryError`` with the reason; the
key is closed whatever happens. Sub-keys (step 4, commit 8) follow the same rules. Writing
(step 4, commit 12a4) is one value under ``HKCU`` only, in the 64-bit view, creating the key if
it is missing; there is no way to write ``HKLM`` (decision 0011, item 8).
"""

import inspect
import sys

import pytest

from kresorter.autostart.registry import (
    Hive,
    Registry,
    RegistryError,
    RegValue,
    UserRegistry,
    ValueKind,
)
from kresorter.autostart.run_keys import APPROVED, RUN, RUN_32
from kresorter.autostart.winregistry import WinRegistry

ERROR_NO_MORE_ITEMS = 259

Raw = tuple[str, object, int]


class NoMoreItemsError(OSError):
    winerror = ERROR_NO_MORE_ITEMS


class MoreDataError(OSError):
    winerror = 234  # ERROR_MORE_DATA: an error, not the end of the values


class FakeKey:
    def __init__(self, path: tuple[int, str], values: list[Raw], subkeys: list[str]) -> None:
        self.path = path
        self.values = values
        self.subkeys = subkeys


class FakeWinreg:
    """Stand-in for ``winreg``: keys by (hive handle, path), with the calls recorded.

    A key exists if it has values (``keys``) or sub-keys (``subkeys``) listed.
    """

    HKEY_CURRENT_USER = 0x80000001
    HKEY_LOCAL_MACHINE = 0x80000002
    KEY_READ = 0x20019
    KEY_SET_VALUE = 0x0002
    KEY_WOW64_64KEY = 0x0100

    def __init__(
        self,
        keys: dict[tuple[int, str], list[Raw]],
        subkeys: dict[tuple[int, str], list[str]] | None = None,
        *,
        open_error: OSError | None = None,
        enum_error: OSError | None = None,
        create_error: OSError | None = None,
        set_error: OSError | None = None,
    ) -> None:
        self._keys = keys
        self._subkeys = subkeys or {}
        self._open_error = open_error
        self._enum_error = enum_error
        self._create_error = create_error
        self._set_error = set_error
        self.opened: list[tuple[int, str, int, int]] = []
        self.created: list[tuple[int, str, int, int]] = []
        self.written: list[tuple[tuple[int, str], str, int, int, object]] = []
        self.closed: list[FakeKey] = []

    def OpenKey(self, key: int, sub_key: str, reserved: int = 0, access: int = 0) -> FakeKey:
        self.opened.append((key, sub_key, reserved, access))
        if self._open_error is not None:
            raise self._open_error
        path = (key, sub_key)
        if path not in self._keys and path not in self._subkeys:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        return FakeKey(path, self._keys.get(path, []), self._subkeys.get(path, []))

    def EnumValue(self, key: object, index: int) -> Raw:
        assert isinstance(key, FakeKey)
        if self._enum_error is not None and index == 1:
            raise self._enum_error
        if index >= len(key.values):
            raise NoMoreItemsError(22, "No more data is available")
        return key.values[index]

    def EnumKey(self, key: object, index: int) -> str:
        assert isinstance(key, FakeKey)
        if self._enum_error is not None and index == 1:
            raise self._enum_error
        if index >= len(key.subkeys):
            raise NoMoreItemsError(22, "No more data is available")
        return key.subkeys[index]

    def CreateKeyEx(self, key: int, sub_key: str, reserved: int = 0, access: int = 0) -> FakeKey:
        """Opens the key, creating it if it is missing, as ``winreg.CreateKeyEx`` does."""
        self.created.append((key, sub_key, reserved, access))
        if self._create_error is not None:
            raise self._create_error
        path = (key, sub_key)
        values = self._keys.setdefault(path, [])
        return FakeKey(path, values, self._subkeys.get(path, []))

    def SetValueEx(self, key: object, name: str, reserved: int, kind: int, data: object) -> None:
        assert isinstance(key, FakeKey)
        self.written.append((key.path, name, reserved, kind, data))
        if self._set_error is not None:
            raise self._set_error
        key.values[:] = [v for v in key.values if v[0].casefold() != name.casefold()]
        key.values.append((name, data, kind))

    def CloseKey(self, key: object) -> None:
        assert isinstance(key, FakeKey)
        self.closed.append(key)


HKCU, HKLM = FakeWinreg.HKEY_CURRENT_USER, FakeWinreg.HKEY_LOCAL_MACHINE
READ_64 = FakeWinreg.KEY_READ | FakeWinreg.KEY_WOW64_64KEY
SET_64 = FakeWinreg.KEY_SET_VALUE | FakeWinreg.KEY_WOW64_64KEY
FLAG = RegValue("Sync", ValueKind.REG_BINARY, b"\x03" + bytes(11))
SERVICES = r"SYSTEM\CurrentControlSet\Services"


def test_it_is_a_registry() -> None:
    registry: Registry = WinRegistry(module=FakeWinreg({}))  # checked by mypy

    assert registry.values(Hive.HKCU, RUN) is None
    assert registry.subkeys(Hive.HKLM, SERVICES) is None


def test_values_are_read_in_order_and_converted() -> None:
    fake = FakeWinreg(
        {
            (HKCU, RUN): [
                ("Sync", r"C:\sync.exe", ValueKind.REG_SZ),
                ("Flag", b"\x02\x00", ValueKind.REG_BINARY),
                ("Count", 7, ValueKind.REG_DWORD),
                ("List", ["a", "b"], ValueKind.REG_MULTI_SZ),
                ("", None, ValueKind.REG_NONE),
            ]
        }
    )

    assert WinRegistry(module=fake).values(Hive.HKCU, RUN) == [
        RegValue("Sync", ValueKind.REG_SZ, r"C:\sync.exe"),
        RegValue("Flag", ValueKind.REG_BINARY, b"\x02\x00"),
        RegValue("Count", ValueKind.REG_DWORD, 7),
        RegValue("List", ValueKind.REG_MULTI_SZ, ["a", "b"]),
        RegValue("", ValueKind.REG_NONE, None),
    ]


def test_keys_are_opened_read_only_in_the_64_bit_view() -> None:
    fake = FakeWinreg({(HKCU, RUN): [], (HKLM, RUN_32): []})
    registry = WinRegistry(module=fake)

    registry.values(Hive.HKCU, RUN)
    registry.values(Hive.HKLM, RUN_32)

    assert fake.opened == [(HKCU, RUN, 0, READ_64), (HKLM, RUN_32, 0, READ_64)]


def test_an_empty_key_has_no_values_and_is_closed() -> None:
    fake = FakeWinreg({(HKCU, RUN): []})

    assert WinRegistry(module=fake).values(Hive.HKCU, RUN) == []
    assert [k.path for k in fake.closed] == [(HKCU, RUN)]


def test_a_missing_key_reads_as_none() -> None:
    fake = FakeWinreg({})

    assert WinRegistry(module=fake).values(Hive.HKCU, RUN) is None
    assert fake.closed == []


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (PermissionError(13, "Access is denied"), "Access is denied"),
        (OSError(1450, "Insufficient system resources"), "Insufficient system resources"),
        (OSError("no strerror"), "no strerror"),
    ],
)
def test_a_key_that_cannot_be_opened_is_a_registry_error(error: OSError, reason: str) -> None:
    registry = WinRegistry(module=FakeWinreg({}, open_error=error))

    with pytest.raises(RegistryError, match=reason):
        registry.values(Hive.HKLM, RUN)


def test_a_failure_while_enumerating_is_an_error_and_the_key_is_still_closed() -> None:
    values: list[Raw] = [("A", "a", ValueKind.REG_SZ), ("B", "b", ValueKind.REG_SZ)]
    fake = FakeWinreg({(HKCU, RUN): values}, enum_error=PermissionError(5, "Access is denied"))

    with pytest.raises(RegistryError, match="Access is denied"):
        WinRegistry(module=fake).values(Hive.HKCU, RUN)

    assert [k.path for k in fake.closed] == [(HKCU, RUN)]


def test_only_no_more_items_ends_the_enumeration() -> None:
    values: list[Raw] = [("A", "a", ValueKind.REG_SZ), ("B", "b", ValueKind.REG_SZ)]
    fake = FakeWinreg({(HKCU, RUN): values}, enum_error=MoreDataError(234, "More data"))

    with pytest.raises(RegistryError, match="More data"):
        WinRegistry(module=fake).values(Hive.HKCU, RUN)


# --- sub-keys ------------------------------------------------------------------------------------


def test_sub_keys_are_read_in_order_read_only_in_the_64_bit_view() -> None:
    fake = FakeWinreg({}, {(HKLM, SERVICES): ["Sync", "Agent"]})

    assert WinRegistry(module=fake).subkeys(Hive.HKLM, SERVICES) == ["Sync", "Agent"]
    assert fake.opened == [(HKLM, SERVICES, 0, READ_64)]
    assert [k.path for k in fake.closed] == [(HKLM, SERVICES)]


def test_a_key_with_values_only_has_no_sub_keys() -> None:
    fake = FakeWinreg({(HKLM, SERVICES): [("A", "a", ValueKind.REG_SZ)]})

    assert WinRegistry(module=fake).subkeys(Hive.HKLM, SERVICES) == []


def test_sub_keys_of_a_missing_key_read_as_none() -> None:
    fake = FakeWinreg({})

    assert WinRegistry(module=fake).subkeys(Hive.HKLM, SERVICES) is None
    assert fake.closed == []


def test_sub_keys_of_a_key_that_cannot_be_opened_are_a_registry_error() -> None:
    fake = FakeWinreg({}, open_error=PermissionError(13, "Access is denied"))

    with pytest.raises(RegistryError, match="Access is denied"):
        WinRegistry(module=fake).subkeys(Hive.HKLM, SERVICES)


@pytest.mark.parametrize(
    "error", [PermissionError(5, "Access is denied"), MoreDataError(234, "More data")]
)
def test_only_no_more_items_ends_the_sub_keys_and_the_key_is_closed(error: OSError) -> None:
    fake = FakeWinreg({}, {(HKLM, SERVICES): ["A", "B"]}, enum_error=error)

    with pytest.raises(RegistryError, match=str(error.strerror)):
        WinRegistry(module=fake).subkeys(Hive.HKLM, SERVICES)

    assert [k.path for k in fake.closed] == [(HKLM, SERVICES)]


@pytest.mark.skipif(sys.platform == "win32", reason="winreg exists there")
def test_winreg_is_imported_lazily() -> None:
    registry = WinRegistry()  # constructing it imports nothing

    with pytest.raises(ModuleNotFoundError, match="winreg"):
        registry.values(Hive.HKCU, RUN)


# --- writing: one value under HKCU ---------------------------------------------------------------


def test_it_is_a_user_registry() -> None:
    registry: UserRegistry = WinRegistry(module=FakeWinreg({}))  # checked by mypy

    assert registry.values(Hive.HKCU, APPROVED) is None


def test_a_value_is_written_under_hkcu_in_the_64_bit_view_and_the_key_closed() -> None:
    fake = FakeWinreg({(HKCU, APPROVED): [("Other", b"\x02", ValueKind.REG_BINARY)]})
    registry = WinRegistry(module=fake)

    registry.set_user_value(APPROVED, FLAG)

    assert fake.created == [(HKCU, APPROVED, 0, SET_64)]
    assert fake.written == [((HKCU, APPROVED), "Sync", 0, ValueKind.REG_BINARY, FLAG.data)]
    assert [k.path for k in fake.closed] == [(HKCU, APPROVED)]
    assert registry.values(Hive.HKCU, APPROVED) == [
        RegValue("Other", ValueKind.REG_BINARY, b"\x02"),
        FLAG,
    ]


def test_a_missing_key_is_created() -> None:
    fake = FakeWinreg({})
    registry = WinRegistry(module=fake)

    registry.set_user_value(APPROVED, FLAG)

    assert registry.values(Hive.HKCU, APPROVED) == [FLAG]


def test_a_key_that_cannot_be_created_is_a_registry_error() -> None:
    fake = FakeWinreg({}, create_error=PermissionError(5, "Access is denied"))

    with pytest.raises(RegistryError, match="Access is denied"):
        WinRegistry(module=fake).set_user_value(APPROVED, FLAG)

    assert (fake.written, fake.closed) == ([], [])


def test_a_value_that_cannot_be_written_is_an_error_and_the_key_is_still_closed() -> None:
    fake = FakeWinreg({}, set_error=OSError(1450, "Insufficient system resources"))

    with pytest.raises(RegistryError, match="Insufficient system resources"):
        WinRegistry(module=fake).set_user_value(APPROVED, FLAG)

    assert [k.path for k in fake.closed] == [(HKCU, APPROVED)]


def test_there_is_no_way_to_write_the_machine_hive() -> None:
    writers = [name for name in dir(WinRegistry) if name.startswith(("set", "delete", "create"))]

    assert writers == ["set_user_value"]
    assert list(inspect.signature(WinRegistry.set_user_value).parameters) == [
        "self",
        "key",
        "value",
    ]
