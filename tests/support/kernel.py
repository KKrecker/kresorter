"""Fakes of Windows' kernel32 for the open-file check (decision 0016): a kernel that records
each call and answers a handle or an error, and the part of ``ctypes`` that ``Kernel32`` takes.
"""

from dataclasses import dataclass, field

INVALID_HANDLE_VALUE = -1


@dataclass
class FakeKernel:
    """``CreateFileW`` answers ``handle``, or -1 and ``error`` as the last error; ``CloseHandle``
    fails with ``close_error`` when it is not 0."""

    handle: int = 7
    error: int = 0
    close_error: int = 0
    calls: list[tuple[object, ...]] = field(default_factory=list)
    _last: int = 0

    def CreateFileW(
        self,
        name: str,
        access: int,
        share: int,
        security: None,
        disposition: int,
        flags: int,
        template: None,
        /,
    ) -> int:
        call = ("CreateFileW", name, access, share, security, disposition, flags, template)
        self.calls.append(call)
        self._last = self.error
        return INVALID_HANDLE_VALUE if self.error else self.handle

    def CloseHandle(self, handle: int, /) -> int:
        self.calls.append(("CloseHandle", handle))
        self._last = self.close_error
        return 0 if self.close_error else 1

    def last_error(self) -> int:
        return self._last

    def message(self, code: int) -> str:
        return f"the message of {code}"


@dataclass
class FakeFunction:
    answer: int
    calls: list[tuple[object, ...]] = field(default_factory=list)
    argtypes: tuple[object, ...] = ()
    restype: object = None

    def __call__(self, *args: object) -> int:
        self.calls.append(args)
        return self.answer


class FakeLibrary:
    def __init__(self) -> None:
        self.CreateFileW = FakeFunction(11)
        self.CloseHandle = FakeFunction(1)


class FakeCtypes:
    """What ``Kernel32`` takes from ``ctypes``: the library, the types, the last error."""

    c_wchar_p = "c_wchar_p"
    c_uint32 = "c_uint32"
    c_void_p = "c_void_p"
    c_ssize_t = "c_ssize_t"
    c_int = "c_int"

    def __init__(self) -> None:
        self.library = FakeLibrary()
        self.loaded: list[tuple[str, bool]] = []

    def WinDLL(self, name: str, *, use_last_error: bool) -> FakeLibrary:
        self.loaded.append((name, use_last_error))
        return self.library

    def get_last_error(self) -> int:
        return 32

    def FormatError(self, code: int) -> str:
        return f"formatted {code}"
