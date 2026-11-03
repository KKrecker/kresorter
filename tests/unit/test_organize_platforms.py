"""Where organize moves files: the blockers of each system (decision 0012, items 37-39, as
decision 0017, items 1 and 2, leaves them).

The reasons behind the table are prose in the decisions ("Why macOS and Windows are refused",
then 0017's context): none of them can be shown on Linux. What is pinned here is the table,
where the open-file blocker comes from, and the message a blocked system gets. Windows lost its
column to 0016 and 0017; macOS keeps its own.
"""

from typing import get_args

import pytest

from fakes import FakeOpenFiles
from kresorter.core.heuristics import Platform
from kresorter.core.open_files import NoOpenFileCheck, checker_for_platform
from kresorter.core.open_files.windows import ShareModeChecker
from kresorter.organize.platforms import Blocker, blockers, refusal
from support.kernel import FakeKernel

# The columns of item 38: what each system blocks whatever its open-file check.
SYSTEM: dict[Platform, tuple[Blocker, ...]] = {
    "linux": (),
    "darwin": (Blocker.CLOUD_SYNC,),
    "windows": (),
}


def test_the_blockers_are_pinned() -> None:
    # [0012.38] [0017.2] adding or removing a blocker is a decision of its own: 0017 took out
    # sharing_violations and path_length_limit
    assert [b.value for b in Blocker] == ["no_open_file_check", "cloud_sync"]


def test_every_system_is_in_the_table() -> None:
    # [0012.38] a new platform gets its column before organize can run there
    assert set(SYSTEM) == set(get_args(Platform))


@pytest.mark.parametrize("platform", list(SYSTEM))
def test_a_reliable_checker_leaves_the_blockers_of_the_system(platform: Platform) -> None:
    # [0012.38] [0012.39] [0017.1] an open-file backend alone does not let organize move on macOS;
    # Windows, with its column empty, sorts as Linux does
    assert blockers(platform, FakeOpenFiles()) == SYSTEM[platform]


@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_an_unreliable_checker_is_the_one_blocker_of_linux_and_windows(platform: Platform) -> None:
    # [0012.39] [0017.1]
    assert blockers(platform, NoOpenFileCheck()) == (Blocker.NO_OPEN_FILE_CHECK,)


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("linux", ()),
        ("darwin", (Blocker.NO_OPEN_FILE_CHECK, Blocker.CLOUD_SYNC)),
        ("windows", ()),
    ],
)
@pytest.mark.usefixtures("kernel32")
def test_with_the_checkers_kresorter_gives_them_macos_alone_is_blocked(
    platform: Platform, expected: tuple[Blocker, ...]
) -> None:
    # [0012.37] [0012.39] [0016.10] [0017.1] (0005; 0016): on Windows the share-mode check lifts
    # the open-file blocker, and 0017 the others
    assert blockers(platform, checker_for_platform(platform)) == expected


def test_windows_with_its_check_refuses_nothing() -> None:
    # [0016.10] [0017.1] organize move and organize undo run there
    assert refusal("windows", ShareModeChecker(FakeKernel())) is None


@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_nothing_to_refuse_where_nothing_blocks(platform: Platform) -> None:
    # [0012.37] [0017.1]
    assert refusal(platform, FakeOpenFiles()) is None


def test_the_refusal_names_the_system_and_every_blocker_in_table_order() -> None:
    # [0012.37] [0012.38] [0017.2] one line per blocker, nothing was changed
    assert refusal("darwin", NoOpenFileCheck()) == (
        "kresorter: organize does not move files on macOS; nothing was changed\n"
        "  - no reliable open-file check: a file a program holds open could be moved"
        " from under it\n"
        "  - Desktop and Documents can be synced to the cloud: a move would reach every device\n"
    )


def test_windows_without_a_reliable_check_is_told_that_alone() -> None:
    # [0017.1] [0017.2] as Linux is: the lines of the blockers it lost are gone
    assert refusal("windows", NoOpenFileCheck()) == (
        "kresorter: organize does not move files on Windows; nothing was changed\n"
        "  - no reliable open-file check: a file a program holds open could be moved"
        " from under it\n"
    )


@pytest.mark.parametrize(
    ("platform", "name"), [("linux", "Linux"), ("darwin", "macOS"), ("windows", "Windows")]
)
def test_the_refusal_names_the_system_as_its_users_do(platform: Platform, name: str) -> None:
    # [0012.37]
    message = refusal(platform, NoOpenFileCheck())
    assert message is not None
    assert message.startswith(f"kresorter: organize does not move files on {name}; ")
