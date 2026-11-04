"""Fakes of Windows' kernel32 for the open-file check (decision 0016): a kernel that records
each call and answers a handle or an error, and the part of ``ctypes`` that ``Kernel32`` takes.
"""

import ntpath
import threading
import time
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


SHARING_VIOLATION = 32


class HoldingKernel(FakeKernel):
    """Windows, where another process holds every file named ``held``: the check's exclusive
    open meets a sharing violation whatever that process shares, deletion included (decision
    0016, item 1). Other files open and close."""

    def __init__(self, held: str) -> None:
        super().__init__()
        self._held = held

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
        self.error = SHARING_VIOLATION if ntpath.basename(name) == self._held else 0
        return super().CreateFileW(name, access, share, security, disposition, flags, template)


class SideBySideKernel:
    """Windows' kernel32 for checks side by side (decision 0018, item 12): each ``CreateFileW``
    waits until ``parties`` checks run at once, and ``most`` is the most that ran at once; a
    file named in ``held`` meets a sharing violation, a later file's check ends first. The last
    error is each thread's own, as ``ctypes`` keeps it."""

    def __init__(self, parties: int, held: set[str]) -> None:
        self._barrier = threading.Barrier(parties, timeout=5)
        self._held = held
        self._lock = threading.Lock()
        self._running = 0
        self._last = threading.local()
        self.most = 0

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
        with self._lock:
            self._running += 1
            self.most = max(self.most, self._running)
        try:
            self._barrier.wait()
        finally:
            with self._lock:
                self._running -= 1
        base = ntpath.basename(name)
        time.sleep(0.02 / (1 + int(base[1:3])))  # f00 last, f15 first
        held = base in self._held
        self._last.code = SHARING_VIOLATION if held else 0
        return INVALID_HANDLE_VALUE if held else 7

    def CloseHandle(self, handle: int, /) -> int:
        return 1

    def last_error(self) -> int:
        code: int = self._last.code
        return code

    def message(self, code: int) -> str:
        return f"the message of {code}"
