"""Where organize moves files: the blockers of each system (decision 0012, items 37-39).

The reasons behind the table are prose in the decision ("Why macOS and Windows are refused"):
none of them can be shown on Linux. What is pinned here is the table, where the open-file
blocker comes from, and the message a blocked system gets.
"""

from typing import get_args

import pytest

from fakes import FakeOpenFiles
from kresorter.core.heuristics import Platform
from kresorter.core.open_files import NoOpenFileCheck, checker_for_platform
from kresorter.organize.platforms import Blocker, blockers, refusal

# The columns of item 38: what each system blocks whatever its open-file check.
SYSTEM: dict[Platform, tuple[Blocker, ...]] = {
    "linux": (),
    "darwin": (Blocker.CLOUD_SYNC,),
    "windows": (Blocker.SHARING_VIOLATIONS, Blocker.PATH_LENGTH_LIMIT, Blocker.CLOUD_SYNC),
}


def test_the_blockers_are_pinned() -> None:
    # [0012.38] adding or removing a blocker is a decision of its own
    assert [b.value for b in Blocker] == [
        "no_open_file_check",
        "sharing_violations",
        "path_length_limit",
        "cloud_sync",
    ]


def test_every_system_is_in_the_table() -> None:
    # [0012.38] a new platform gets its column before organize can run there
    assert set(SYSTEM) == set(get_args(Platform))


@pytest.mark.parametrize("platform", list(SYSTEM))
def test_a_reliable_checker_leaves_the_blockers_of_the_system(platform: Platform) -> None:
    # [0012.38] [0012.39] an open-file backend alone does not let organize move on macOS or Windows
    assert blockers(platform, FakeOpenFiles()) == SYSTEM[platform]


def test_an_unreliable_checker_blocks_linux_too() -> None:
    # [0012.39]
    assert blockers("linux", NoOpenFileCheck()) == (Blocker.NO_OPEN_FILE_CHECK,)


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("linux", ()),
        ("darwin", (Blocker.NO_OPEN_FILE_CHECK, Blocker.CLOUD_SYNC)),
        ("windows", tuple(Blocker)),
    ],
)
def test_today_macos_and_windows_have_every_blocker_of_their_column(
    platform: Platform, expected: tuple[Blocker, ...]
) -> None:
    # [0012.37] [0012.39] with the checkers kresorter gives them (0005; 0004 item 9)
    assert blockers(platform, checker_for_platform(platform)) == expected


def test_nothing_to_refuse_where_nothing_blocks() -> None:
    # [0012.37]
    assert refusal("linux", FakeOpenFiles()) is None


def test_the_refusal_names_the_system_and_every_blocker_in_table_order() -> None:
    # [0012.37] [0012.38] one line per blocker, nothing was changed
    assert refusal("windows", NoOpenFileCheck()) == (
        "kresorter: organize does not move files on Windows; nothing was changed\n"
        "  - no reliable open-file check: a file a program holds open could be moved"
        " from under it\n"
        "  - a file another program holds open can refuse to move halfway through a batch,"
        " and so can the move back\n"
        "  - one directory deeper, a path can pass the 260-character limit\n"
        "  - Desktop and Documents can be synced to the cloud: a move would reach every device\n"
    )


@pytest.mark.parametrize(
    ("platform", "name"), [("linux", "Linux"), ("darwin", "macOS"), ("windows", "Windows")]
)
def test_the_refusal_names_the_system_as_its_users_do(platform: Platform, name: str) -> None:
    # [0012.37]
    message = refusal(platform, NoOpenFileCheck())
    assert message is not None
    assert message.startswith(f"kresorter: organize does not move files on {name}; ")
