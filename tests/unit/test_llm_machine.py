"""The machine's memory and processors, and the model recommended for them (decision 0018,
item 33): ``qwen2.5``, for its languages, Russian among them, sized by the memory, one size
smaller with fewer than four processors; unknown as the least."""

import ctypes
import os
import sys
from dataclasses import dataclass, field

import pytest

from kresorter.core.heuristics import Platform
from kresorter.llm.machine import (
    GIB,
    LMSTUDIO_RECOMMENDED,
    RECOMMENDED,
    Machine,
    MemoryStatus,
    recommended,
    this_machine,
)

live = pytest.mark.skipif(sys.platform != "win32", reason="live Windows memory")


@dataclass
class FakeQuery:
    """``GlobalMemoryStatusEx``: writes ``total`` as the physical memory, answers ``answer``."""

    total: int
    answer: int = 1
    lengths: list[int] = field(default_factory=list)
    argtypes: tuple[object, ...] = ()
    restype: object = None

    def __call__(self, status: MemoryStatus, /) -> int:
        self.lengths.append(status.dwLength)
        status.ullTotalPhys = self.total
        return self.answer


class FakeKernel:
    def __init__(self, query: FakeQuery) -> None:
        self.GlobalMemoryStatusEx = query


class FakeCtypes:
    """What the memory's look takes from ``ctypes``: kernel32."""

    def __init__(self, query: FakeQuery) -> None:
        self.kernel = FakeKernel(query)
        self.loaded: list[tuple[str, bool]] = []

    def WinDLL(self, name: str, *, use_last_error: bool) -> FakeKernel:
        self.loaded.append((name, use_last_error))
        return self.kernel


# --- the model recommended -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("memory", "processors", "model"),
    [
        (4 * GIB, 8, "qwen2.5:1.5b"),
        (8 * GIB - 1, 8, "qwen2.5:1.5b"),
        (8 * GIB, 8, "qwen2.5:3b"),
        (16 * GIB - 1, 4, "qwen2.5:3b"),
        (16 * GIB, 4, "qwen2.5:7b"),
        (32 * GIB - 1, 16, "qwen2.5:7b"),
        (32 * GIB, 16, "qwen2.5:14b"),
        (256 * GIB, 64, "qwen2.5:14b"),
        (64 * GIB, 3, "qwen2.5:7b"),
        (16 * GIB, 2, "qwen2.5:3b"),
        (8 * GIB, 1, "qwen2.5:1.5b"),
        (4 * GIB, 1, "qwen2.5:1.5b"),
        (None, 8, "qwen2.5:1.5b"),
        (64 * GIB, None, "qwen2.5:7b"),
    ],
)
def test_the_model_recommended_for_the_memory_and_the_processors(
    memory: int | None, processors: int | None, model: str
) -> None:
    # [0018.33] One size smaller with fewer than four processors, none smaller than the least;
    # an unknown memory as under 8 GiB, unknown processors as fewer than four.
    assert recommended(Machine(memory, processors)) == model


def test_the_models_recommended_are_qwen2_5_s() -> None:
    # [0018.33]
    assert RECOMMENDED == ("qwen2.5:1.5b", "qwen2.5:3b", "qwen2.5:7b", "qwen2.5:14b")
    assert GIB == 1 << 30


@pytest.mark.parametrize(
    ("memory", "processors", "model"),
    [
        (4 * GIB, 8, "qwen2.5-1.5b-instruct"),
        (8 * GIB, 8, "qwen2.5-3b-instruct"),
        (16 * GIB, 4, "qwen2.5-7b-instruct"),
        (32 * GIB, 16, "qwen2.5-14b-instruct"),
        (64 * GIB, 3, "qwen2.5-7b-instruct"),
        (None, None, "qwen2.5-1.5b-instruct"),
    ],
)
def test_lm_studio_s_recommendation_is_the_same_model_as_lm_studio_names_it(
    memory: int | None, processors: int | None, model: str
) -> None:
    # [0019.13] The size Ollama's would be, by LM Studio's name.
    machine = Machine(memory, processors)
    assert recommended(machine, "lmstudio") == model
    assert recommended(machine, "ollama") == recommended(machine)
    assert LMSTUDIO_RECOMMENDED.index(model) == RECOMMENDED.index(recommended(machine))


def test_the_models_recommended_for_lm_studio() -> None:
    # [0019.13]
    assert LMSTUDIO_RECOMMENDED == (
        "qwen2.5-1.5b-instruct",
        "qwen2.5-3b-instruct",
        "qwen2.5-7b-instruct",
        "qwen2.5-14b-instruct",
    )


# --- the machine ---------------------------------------------------------------------------------


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_elsewhere_the_memory_is_the_system_s_pages(
    monkeypatch: pytest.MonkeyPatch, platform: Platform
) -> None:
    # [0018.33] os.sysconf: the page size times the physical pages; the processors os's.
    pages = {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 4 * 1024 * 1024}
    monkeypatch.setattr(os, "sysconf", lambda name: pages[name], raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 6)
    assert this_machine(platform) == Machine(16 * GIB, 6)


@pytest.mark.parametrize("error", [ValueError("SC_PHYS_PAGES"), OSError(22, "Invalid argument")])
def test_a_memory_the_system_does_not_say_is_unknown(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    # [0018.33]
    def refused(name: str) -> int:
        raise error

    monkeypatch.setattr(os, "sysconf", refused, raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert this_machine("linux") == Machine(None, None)


def test_on_windows_the_memory_is_global_memory_status_ex_s(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0018.33] Its structure's length set first, as the call wants it.
    query = FakeQuery(32 * GIB)
    found = FakeCtypes(query)
    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    assert this_machine("windows", ctypes_module=found) == Machine(32 * GIB, 12)
    assert found.loaded == [("kernel32", True)]
    assert query.lengths == [ctypes.sizeof(MemoryStatus)] == [64]
    assert query.restype is ctypes.c_int


def test_a_call_that_fails_is_an_unknown_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    # [0018.33]
    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    found = FakeCtypes(FakeQuery(32 * GIB, answer=0))
    assert this_machine("windows", ctypes_module=found) == Machine(None, 2)


@live
def test_the_memory_of_this_windows_machine() -> None:
    # [0018.33]
    found = this_machine("windows")
    assert found.memory is not None
    assert found.memory > GIB // 2
