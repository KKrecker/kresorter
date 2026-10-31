"""The adapter from the ``Registry`` protocol to the real ``winreg`` (step 4, commit 6; 0011).

``winreg`` exists only on Windows, so it is imported on first use and the tests drive the
adapter with a stand-in module, like ``MsvcrtBackend`` (decision 0009). Keys are opened for
reading in the 64-bit view, so an explicit ``WOW6432Node`` path means exactly that key. A
missing key reads as ``None``; any other failure is a ``RegistryError`` with the reason; the
key is closed whatever happens.
"""

import sys

import pytest

from safeclean.autostart.registry import Hive, Registry, RegistryError, RegValue, ValueKind
from safeclean.autostart.run_keys import RUN, RUN_32
from safeclean.autostart.winregistry import WinRegistry

ERROR_NO_MORE_ITEMS = 259

Raw = tuple[str, object, int]


class NoMoreItemsError(OSError):
    winerror = ERROR_NO_MORE_ITEMS


class MoreDataError(OSError):
    winerror = 234  # ERROR_MORE_DATA: an error, not the end of the values


class FakeKey:
    def __init__(self, path: tuple[int, str], values: list[Raw]) -> None:
        self.path = path
        self.values = values


class FakeWinreg:
    """Stand-in for ``winreg``: keys by (hive handle, path), with the calls recorded."""

    HKEY_CURRENT_USER = 0x80000001
    HKEY_LOCAL_MACHINE = 0x80000002
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x0100

    def __init__(
        self,
        keys: dict[tuple[int, str], list[Raw]],
        *,
        open_error: OSError | None = None,
        enum_error: OSError | None = None,
    ) -> None:
        self._keys = keys
        self._open_error = open_error
        self._enum_error = enum_error
        self.opened: list[tuple[int, str, int, int]] = []
        self.closed: list[FakeKey] = []

    def OpenKey(self, key: int, sub_key: str, reserved: int = 0, access: int = 0) -> FakeKey:
        self.opened.append((key, sub_key, reserved, access))
        if self._open_error is not None:
            raise self._open_error
        if (key, sub_key) not in self._keys:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        return FakeKey((key, sub_key), self._keys[(key, sub_key)])

    def EnumValue(self, key: object, index: int) -> Raw:
        assert isinstance(key, FakeKey)
        if self._enum_error is not None and index == 1:
            raise self._enum_error
        if index >= len(key.values):
            raise NoMoreItemsError(22, "No more data is available")
        return key.values[index]

    def CloseKey(self, key: object) -> None:
        assert isinstance(key, FakeKey)
        self.closed.append(key)


HKCU, HKLM = FakeWinreg.HKEY_CURRENT_USER, FakeWinreg.HKEY_LOCAL_MACHINE
READ_64 = FakeWinreg.KEY_READ | FakeWinreg.KEY_WOW64_64KEY


def test_it_is_a_registry() -> None:
    registry: Registry = WinRegistry(module=FakeWinreg({}))  # checked by mypy

    assert registry.values(Hive.HKCU, RUN) is None


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


@pytest.mark.skipif(sys.platform == "win32", reason="winreg exists there")
def test_winreg_is_imported_lazily() -> None:
    registry = WinRegistry()  # constructing it imports nothing

    with pytest.raises(ModuleNotFoundError, match="winreg"):
        registry.values(Hive.HKCU, RUN)
