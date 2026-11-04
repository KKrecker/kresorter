"""What failed on CI, readable without signing in (decision 0015, item 20): the failures of a
run become annotations of its job, a block for each place they were raised at
(``support.annotations``, written by ``conftest.pytest_terminal_summary``).
"""

from types import SimpleNamespace

from support.annotations import (
    BLOCK,
    DEPTH,
    LIMIT,
    NAMED,
    SIZE,
    WIDE,
    Failure,
    commands,
    failure,
    failures,
)

ROOT = "C:\\a\\kresorter"


def frame(path: str, lineno: int, *lines: str) -> SimpleNamespace:
    return SimpleNamespace(reprfileloc=SimpleNamespace(path=path, lineno=lineno), lines=list(lines))


def crashed(message: str, *frames: SimpleNamespace) -> SimpleNamespace:
    crash = SimpleNamespace(path=ROOT + "\\src\\x.py", lineno=28, message=message)
    return SimpleNamespace(reprcrash=crash, reprtraceback=SimpleNamespace(reprentries=frames))


def message(command: str) -> list[str]:
    return command.split("::", 2)[2].split("%0A")


def title(command: str) -> str:
    return command.split("::", 2)[1].removeprefix("error title=")


def test_a_failure_is_where_it_was_raised_from_the_root_with_its_traceback() -> None:
    # [0015.20] a Windows path is read from the repository's root, with slashes
    longrepr = crashed(
        "ValueError: relative\nmore",
        frame("tests\\test_x.py", 5, "    def test_a():", ">       helper([])"),
        frame("native.py", 1),
        SimpleNamespace(reprfileloc=None, lines=[">ignored"]),
        frame(
            ROOT + "\\src\\x.py", 28, "  def helper(x):", ">   raise E", "E   ValueError: a", "E"
        ),
    )
    assert failure("tests/test_x.py::test_a", longrepr, ROOT) == Failure(
        "tests/test_x.py::test_a",
        "ValueError: relative",
        "src/x.py:28",
        "tests/test_x.py:5: helper([])\nnative.py:1\nsrc/x.py:28: raise E\nValueError: a\n",
    )


def test_a_traceback_keeps_its_last_frames_and_its_lines_their_width() -> None:
    # [0015.20]
    frames = [frame(f"f{n}.py", n, f">   step{n}()") for n in range(DEPTH + 2)]
    long = "x" * WIDE
    longrepr = crashed("E", *frames, frame("g.py", 9, ">" + long, "E   " + long))
    detail = failure("t", longrepr, ROOT).detail.splitlines()
    assert detail[0] == "f3.py:3: step3()"
    assert len(detail) == DEPTH + 1
    assert detail[-2] == "g.py:9: " + long[: WIDE - 11] + "..."
    assert detail[-1] == long
    assert failure("t", SimpleNamespace(reprcrash=longrepr.reprcrash), ROOT).detail == ""


def test_a_failure_with_no_crash_is_its_last_line_at_no_place() -> None:
    # [0015.20] an error of a fixture or of the collection may be text only
    found = failure("tests/test_x.py", "Traceback\n  line\nImportError: x\n", ROOT)
    assert found == Failure("tests/test_x.py", "ImportError: x", "")
    assert failure("t", "", ROOT) == Failure("t", "", "")


def test_the_tests_failed_then_those_in_error() -> None:
    # [0015.20]
    def report(nodeid: str) -> SimpleNamespace:
        return SimpleNamespace(nodeid=nodeid, longrepr=crashed("E", frame("t.py", 1)))

    stats = {"passed": [report("p")], "error": [report("e")], "failed": [report("f")]}
    assert [one.test for one in failures(stats, ROOT)] == ["f", "e"]
    assert failures({}, ROOT) == []


def test_a_block_a_place_the_place_most_fail_at_first() -> None:
    # [0015.20] the tests one fault fails are one block, with the first one's traceback
    found = commands(
        [
            Failure("t1", "A", "x.py:1"),
            Failure("t2", "B", "y.py:2", "y.py:2: f()\nB"),
            Failure("t3", "B2", "y.py:2", "other"),
        ]
    )
    assert found == [
        "::error title=2 failed at y.py%3A2%3A B::"
        "== 2 failed at y.py:2: B%0Ay.py:2: f()%0AB%0At2%0At3%0A== 1 failed at x.py:1: A%0At1"
    ]
    (nowhere,) = commands([Failure("t", "E", "")])
    assert nowhere == "::error title=1 failed at no place%3A E::== 1 failed at no place: E%0At"
    assert commands([]) == []


def test_a_block_names_twenty_tests_and_is_cut_to_its_size() -> None:
    # [0015.20]
    (one,) = commands([Failure(f"t{n}", "E", "x.py:1") for n in range(NAMED + 5)])
    assert message(one)[1:] == [f"t{n}" for n in range(NAMED)] + ["and 5 more"]
    (named,) = commands([Failure(f"t{n}", "E", "x.py:1") for n in range(NAMED)])
    assert message(named)[1:] == [f"t{n}" for n in range(NAMED)]
    (wide,) = commands([Failure("t" * WIDE, "e" * WIDE, "x.py:1")])
    heading = "1 failed at x.py:1: " + "e" * (WIDE - 23) + "..."
    assert message(wide) == ["== " + heading, "t" * (WIDE // 2 - 3) + "..."]
    (big,) = commands([Failure("t", "E", "x.py:1", "d" * BLOCK)])
    heading = "== 1 failed at x.py:1: E"
    assert message(big) == [heading, "d" * (BLOCK - len(heading) - 4) + "..."]


def test_an_annotation_is_escaped() -> None:
    # [0015.20] a command is one line, its title has no colon or comma of its own
    (odd,) = commands([Failure("a,b", "50%\r", "x.py:1")])
    assert (
        odd
        == "::error title=1 failed at x.py%3A1%3A 50%25%0D::== 1 failed at x.py:1: 50%25%0D%0Aa,b"
    )


def test_the_blocks_fill_ten_annotations_the_rest_counted_at_the_end() -> None:
    # [0015.20] GitHub keeps ten errors of a step, each up to about 4000 characters
    places = 3 * LIMIT + 2
    found = commands([Failure(f"t{n}", "E", f"p{n}.py:1", "d" * 1250) for n in range(places)])
    blocks = [[line for line in message(one) if line.startswith("== ")] for one in found]
    assert [len(theirs) for theirs in blocks] == [3] * (LIMIT - 1) + [2]
    assert [title(one) for one in found[:2]] == [
        "1 failed at p0.py%3A1%3A E",
        "1 failed at p3.py%3A1%3A E",
    ]
    assert message(found[-1])[-1] == "and 3 failed at 3 more places: p29.py:1, p30.py:1, p31.py:1"
    assert all(len("\n".join(message(one))) <= SIZE for one in found)
    assert (
        len(commands([Failure(f"t{n}", "E", f"p{n}.py:1", "d" * 1250) for n in range(30)])) == LIMIT
    )
