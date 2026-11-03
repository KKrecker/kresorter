"""The Windows open-file check: an exclusive open, closed at once (decision 0016, items 1-4, 6).

Every system runs these through a fake kernel that records each call and answers a handle or an
error; ``Kernel32``, the default, is checked against a fake ``ctypes``. What only Windows can
show is in the live tests (item 7).
"""

from pathlib import PureWindowsPath

import pytest

from kresorter.core.open_files import OpenFileCheckError
from kresorter.core.open_files.windows import Kernel, Kernel32, ShareModeChecker
from kresorter.core.policy import BlockReason, PathPolicy, Verdict
from support.kernel import FakeCtypes, FakeKernel

GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
FLAGS = 0x00200000 | 0x00100000  # FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_OPEN_NO_RECALL
SHARING_VIOLATION = 32
FILE = PureWindowsPath(r"C:\Users\Alice\Downloads\a.txt")


def opened(name: str) -> tuple[object, ...]:
    return ("CreateFileW", name, GENERIC_READ, 0, None, OPEN_EXISTING, FLAGS, None)


def test_a_fake_kernel_is_a_kernel() -> None:
    # [0016.6] the protocol the checker takes
    kernel: Kernel = FakeKernel()
    assert ShareModeChecker(kernel).reliable is True


def test_a_handle_is_not_open_and_is_closed_at_once() -> None:
    # [0016.1] [0016.3] read access, share mode 0, no reparse point followed, no recall
    kernel = FakeKernel(handle=7)
    assert ShareModeChecker(kernel).is_open(FILE) is False
    assert kernel.calls == [opened(r"\\?\C:\Users\Alice\Downloads\a.txt"), ("CloseHandle", 7)]


def test_a_sharing_violation_is_open() -> None:
    # [0016.1] nothing to close
    kernel = FakeKernel(error=SHARING_VIOLATION)
    assert ShareModeChecker(kernel).is_open(FILE) is True
    assert kernel.calls == [opened(r"\\?\C:\Users\Alice\Downloads\a.txt")]


@pytest.mark.parametrize("code", [2, 3, 5, 1920])
def test_any_other_error_fails_closed(code: int) -> None:
    # [0016.2] gone, no path, access denied, a file the system cannot reach: the code and
    # the message
    kernel = FakeKernel(error=code)
    with pytest.raises(OpenFileCheckError) as raised:
        ShareModeChecker(kernel).is_open(FILE)
    assert str(raised.value) == f"cannot check {FILE}: Windows error {code}: the message of {code}"
    assert len(kernel.calls) == 1


def test_a_handle_that_cannot_be_closed_fails_closed() -> None:
    # [0016.2]
    kernel = FakeKernel(handle=9, close_error=6)
    with pytest.raises(OpenFileCheckError) as raised:
        ShareModeChecker(kernel).is_open(FILE)
    message = f"cannot close the check of {FILE}: Windows error 6: the message of 6"
    assert str(raised.value) == message
    assert kernel.calls[-1] == ("CloseHandle", 9)


def test_the_policy_takes_a_failing_check_for_open() -> None:
    # [0016.2] (0005)
    policy = PathPolicy.for_windows({"USERPROFILE": r"C:\Users\Alice"})
    verdict = policy.check_file(FILE, ShareModeChecker(FakeKernel(error=5)))
    assert verdict == Verdict(allowed=False, reason=BlockReason.OPEN_FILE)


@pytest.mark.parametrize(
    ("path", "name"),
    [
        pytest.param(
            "C:\\" + "d" * 300 + "\\a.txt", "\\\\?\\C:\\" + "d" * 300 + "\\a.txt", id="long"
        ),
        pytest.param(r"\\server\share\dir\a.txt", r"\\?\UNC\server\share\dir\a.txt", id="share"),
        pytest.param(r"\\?\C:\already\a.txt", r"\\?\C:\already\a.txt", id="prefixed"),
        pytest.param("C:/Users/Alice/../Bob/a.txt", r"\\?\C:\Users\Bob\a.txt", id="made-absolute"),
    ],
)
def test_the_path_is_given_whole_with_its_prefix(path: str, name: str) -> None:
    # [0016.4] a path over 260 characters is checked like any other
    kernel = FakeKernel()
    ShareModeChecker(kernel).is_open(PureWindowsPath(path))
    assert kernel.calls[0] == opened(name)


# --- Kernel32: kernel32 through ctypes ----------------------------------------------------------


def test_kernel32_is_loaded_with_its_last_error_and_typed() -> None:
    # [0016.6] a handle as a signed integer: INVALID_HANDLE_VALUE is -1
    module = FakeCtypes()
    Kernel32(module)
    create, close = module.library.CreateFileW, module.library.CloseHandle
    assert module.loaded == [("kernel32", True)]
    assert create.argtypes == (
        "c_wchar_p",
        "c_uint32",
        "c_uint32",
        "c_void_p",
        "c_uint32",
        "c_uint32",
        "c_void_p",
    )
    assert (create.restype, close.argtypes, close.restype) == ("c_ssize_t", ("c_void_p",), "c_int")


def test_kernel32_passes_each_call_on() -> None:
    # [0016.6]
    module = FakeCtypes()
    kernel = Kernel32(module)
    assert kernel.CreateFileW("n", GENERIC_READ, 0, None, OPEN_EXISTING, FLAGS, None) == 11
    assert kernel.CloseHandle(11) == 1
    assert (kernel.last_error(), kernel.message(5)) == (32, "formatted 5")
    assert module.library.CreateFileW.calls == [
        ("n", GENERIC_READ, 0, None, OPEN_EXISTING, FLAGS, None)
    ]
    assert module.library.CloseHandle.calls == [(11,)]


def test_the_default_kernel_is_loaded_when_the_checker_is_made(kernel32: FakeCtypes) -> None:
    # [0016.6]
    checker = ShareModeChecker()
    assert kernel32.loaded == [("kernel32", True)]
    assert checker.is_open(FILE) is False
    assert kernel32.library.CloseHandle.calls == [(11,)]
