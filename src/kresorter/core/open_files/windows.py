r"""Windows open-file backend: an exclusive open, closed at once (decision 0016, items 1-4, 6).

``CreateFileW`` with read access and share mode 0 is refused with ``ERROR_SHARING_VIOLATION``
while any handle reads, writes or deletes the file: the kernel checks it on the file itself, for
every process and every user, through every hard link. The handle, when there is one, is closed
at once: no byte is read, no lock is kept. A reparse point is not followed and a file kept in the
cloud is not downloaded. The path is given absolute with ``\\?\`` (``\\?\UNC\`` for a share), so
its length does not matter. Any other error, and a handle that cannot be closed, raise
``OpenFileCheckError``, which the policy takes for "open".

Limitation (decision 0016): a handle opened for attributes only, and a file mapped into memory
whose handle was closed, are not seen.
"""

from __future__ import annotations

import importlib
import ntpath
from pathlib import PurePath
from typing import Protocol, cast

from kresorter.core.open_files.base import OpenFileCheckError

__all__ = ["Kernel", "Kernel32", "ShareModeChecker"]

GENERIC_READ = 0x80000000
NO_SHARING = 0
OPEN_EXISTING = 3
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_FLAG_OPEN_NO_RECALL = 0x00100000
INVALID_HANDLE_VALUE = -1  # a handle is a signed integer here (Kernel32)
ERROR_SHARING_VIOLATION = 32
_EXTENDED = "\\\\?\\"
_SHARE = "\\\\"


class Kernel(Protocol):
    """The calls the check needs: kernel32's two, the last error and its message."""

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
    ) -> int: ...

    def CloseHandle(self, handle: int, /) -> int: ...

    def last_error(self) -> int: ...

    def message(self, code: int) -> str: ...


class _Function(Protocol):
    argtypes: tuple[object, ...]
    restype: object

    def __call__(self, *args: object) -> int: ...


class _Library(Protocol):
    @property
    def CreateFileW(self) -> _Function: ...

    @property
    def CloseHandle(self) -> _Function: ...


class _Ctypes(Protocol):
    """What ``Kernel32`` takes from ``ctypes``: the library, the types, the last error."""

    @property
    def c_wchar_p(self) -> object: ...

    @property
    def c_uint32(self) -> object: ...

    @property
    def c_void_p(self) -> object: ...

    @property
    def c_ssize_t(self) -> object: ...

    @property
    def c_int(self) -> object: ...

    def WinDLL(self, name: str, *, use_last_error: bool) -> _Library: ...

    def get_last_error(self) -> int: ...

    def FormatError(self, code: int) -> str: ...


class Kernel32:
    """kernel32 through ``ctypes``, Windows only; ``module`` is ``ctypes`` unless a test gives
    one. The last error is the one ``ctypes`` saved after each call."""

    def __init__(self, module: _Ctypes | None = None) -> None:
        found = module or cast("_Ctypes", importlib.import_module("ctypes"))
        library = found.WinDLL("kernel32", use_last_error=True)
        create, close = library.CreateFileW, library.CloseHandle
        word, pointer = found.c_uint32, found.c_void_p
        create.argtypes = (found.c_wchar_p, word, word, pointer, word, word, pointer)
        create.restype = found.c_ssize_t
        close.argtypes = (pointer,)
        close.restype = found.c_int
        self._ctypes, self._create, self._close = found, create, close

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
        return self._create(name, access, share, security, disposition, flags, template)

    def CloseHandle(self, handle: int, /) -> int:
        return self._close(handle)

    def last_error(self) -> int:
        return self._ctypes.get_last_error()

    def message(self, code: int) -> str:
        return self._ctypes.FormatError(code)


def extended(path: PurePath) -> str:
    r"""``path`` absolute, with ``\\?\`` (``\\?\UNC\`` for a share)."""
    text = str(path)
    if text.startswith(_EXTENDED):
        return text
    text = ntpath.abspath(text)
    if text.startswith(_SHARE):
        return f"{_EXTENDED}UNC\\{text[len(_SHARE) :]}"
    return _EXTENDED + text


class ShareModeChecker:
    """``reliable``: the kernel answers for every process. ``kernel``: ``Kernel32`` unless a
    test gives one, loaded here."""

    def __init__(self, kernel: Kernel | None = None) -> None:
        self._kernel = kernel or Kernel32()

    @property
    def reliable(self) -> bool:
        return True

    def is_open(self, path: PurePath) -> bool:
        kernel = self._kernel
        flags = FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_OPEN_NO_RECALL
        name = extended(path)
        handle = kernel.CreateFileW(
            name, GENERIC_READ, NO_SHARING, None, OPEN_EXISTING, flags, None
        )
        if handle == INVALID_HANDLE_VALUE:
            code = kernel.last_error()
            if code == ERROR_SHARING_VIOLATION:
                return True
            raise OpenFileCheckError(f"cannot check {path}: {self._error(code)}")
        if not kernel.CloseHandle(handle):
            code = kernel.last_error()
            raise OpenFileCheckError(f"cannot close the check of {path}: {self._error(code)}")
        return False

    def _error(self, code: int) -> str:
        return f"Windows error {code}: {self._kernel.message(code)}"
