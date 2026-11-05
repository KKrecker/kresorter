"""The machine's memory and processors, and the model recommended for them (decision 0018,
item 33; decision 0020, item 11).

Qwen3, for its languages, Russian among them, and for its instruct models, which do not think
(under 8 GiB the 1.7B, which is told not to): sized by the memory, one size smaller with fewer
than four processors; for LM Studio, the same model as LM Studio names it (decision 0019,
item 13). The memory is ``GlobalMemoryStatusEx``'s
on Windows and ``os.sysconf``'s elsewhere; a memory or a number of processors the system does
not say is taken for the least. kresorter recommends; it installs nothing.
"""

from __future__ import annotations

import ctypes
import importlib
import os
from dataclasses import dataclass
from typing import Protocol, cast

from kresorter.llm.settings import Server

__all__ = [
    "GIB",
    "LMSTUDIO_RECOMMENDED",
    "RECOMMENDED",
    "Machine",
    "MemoryStatus",
    "recommended",
    "this_machine",
]

GIB = 1 << 30
# The 30B is a mixture of experts with 3B active: on a processor, about as fast as a 3B model.
RECOMMENDED = ("qwen3:1.7b", "qwen3:4b-instruct", "qwen3:30b-instruct")
LMSTUDIO_RECOMMENDED = ("qwen/qwen3-1.7b", "qwen/qwen3-4b-2507", "qwen/qwen3-30b-a3b-2507")
_NAMES: dict[Server, tuple[str, ...]] = {"ollama": RECOMMENDED, "lmstudio": LMSTUDIO_RECOMMENDED}
_SIZES = (8 * GIB, 32 * GIB)  # under each, the model of its place
_FEW_PROCESSORS = 4


@dataclass(frozen=True)
class Machine:
    """The physical memory in bytes and the logical processors; ``None`` when not known."""

    memory: int | None
    processors: int | None


def recommended(machine: Machine, server: Server = "ollama") -> str:
    """The model for ``machine``, by ``server``'s name for it."""
    memory = machine.memory or 0
    size = sum(memory >= least for least in _SIZES)
    if (machine.processors or 0) < _FEW_PROCESSORS:
        size = max(size - 1, 0)
    return _NAMES[server][size]


class MemoryStatus(ctypes.Structure):
    """``MEMORYSTATUSEX``: its length set before the call, the physical memory after it."""

    _fields_ = (
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    )
    dwLength: int
    ullTotalPhys: int


class _Function(Protocol):
    argtypes: tuple[object, ...]
    restype: object

    def __call__(self, status: MemoryStatus, /) -> int: ...


class _Library(Protocol):
    @property
    def GlobalMemoryStatusEx(self) -> _Function: ...


class _Ctypes(Protocol):
    """What the memory's look takes from ``ctypes``: kernel32."""

    def WinDLL(self, name: str, *, use_last_error: bool) -> _Library: ...


class _System(Protocol):
    """``os.sysconf``, which Windows has not."""

    def sysconf(self, name: str, /) -> int: ...


def _windows_memory(module: _Ctypes | None) -> int | None:
    found = module or cast("_Ctypes", importlib.import_module("ctypes"))
    query = found.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
    query.argtypes = (ctypes.POINTER(MemoryStatus),)
    query.restype = ctypes.c_int
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if query(status) == 0:
        return None
    return status.ullTotalPhys


def _memory_elsewhere() -> int | None:
    system = cast("_System", os)
    try:
        return system.sysconf("SC_PAGE_SIZE") * system.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError):
        return None


def this_machine(platform: str, ctypes_module: _Ctypes | None = None) -> Machine:
    """This machine's, ``platform`` its system (``windows``, ``linux`` or ``darwin``, as
    ``kresorter.core.heuristics.Platform``); ``ctypes_module`` is ``ctypes`` unless a test gives
    one."""
    memory = _windows_memory(ctypes_module) if platform == "windows" else _memory_elsewhere()
    return Machine(memory, os.cpu_count())
