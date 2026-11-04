"""What failed on CI, readable without signing in (decision 0015, item 20): the failures of a
run become annotations of its job, one for each place they were raised at
(``support.annotations``, written by ``conftest.pytest_terminal_summary``).
"""

from types import SimpleNamespace

from support.annotations import LIMIT, NAMED, WIDE, Failure, commands, failure, failures

ROOT = "C:\\a\\kresorter"


def crashed(path: str, lineno: int, message: str) -> SimpleNamespace:
    return SimpleNamespace(reprcrash=SimpleNamespace(path=path, lineno=lineno, message=message))


def test_a_failure_is_its_first_line_where_it_was_raised_from_the_root() -> None:
    # [0015.20] a Windows path is read from the repository's root, with slashes
    longrepr = crashed(ROOT + "\\src\\kresorter\\x.py", 28, "ValueError: relative\nmore")
    found = failure("tests/test_x.py::test_a", longrepr, ROOT)
    assert found == Failure(
        "tests/test_x.py::test_a", "ValueError: relative", "src/kresorter/x.py:28"
    )


def test_a_failure_with_no_crash_is_its_last_line_at_no_place() -> None:
    # [0015.20] an error of a fixture or of the collection may be text only
    found = failure("tests/test_x.py", "Traceback\n  line\nImportError: x\n", ROOT)
    assert found == Failure("tests/test_x.py", "ImportError: x", "")
    assert failure("t", "", ROOT) == Failure("t", "", "")


def test_the_tests_failed_then_those_in_error() -> None:
    # [0015.20]
    def report(nodeid: str) -> SimpleNamespace:
        return SimpleNamespace(nodeid=nodeid, longrepr=crashed(ROOT + "/t.py", 1, "E"))

    stats = {"passed": [report("p")], "error": [report("e")], "failed": [report("f")]}
    assert [one.test for one in failures(stats, ROOT)] == ["f", "e"]
    assert failures({}, ROOT) == []


def test_one_annotation_a_place_the_place_most_fail_at_first() -> None:
    # [0015.20] the tests one fault fails are one annotation
    found = commands(
        [
            Failure("t1", "A", "x.py:1"),
            Failure("t2", "B", "y.py:2"),
            Failure("t3", "B2", "y.py:2"),
        ]
    )
    assert found == [
        "::error title=2 failed at y.py%3A2%3A B::t2: B%0At3: B2",
        "::error title=1 failed at x.py%3A1%3A A::t1: A",
    ]
    assert commands([Failure("t", "E", "")]) == ["::error title=1 failed at no place%3A E::t: E"]
    assert commands([]) == []


def test_a_step_keeps_ten_errors_the_last_counts_the_rest() -> None:
    # [0015.20] GitHub keeps ten errors of a step
    places = LIMIT + 2
    found = commands(
        [
            Failure(f"t{place}-{n}", f"E{place}", f"p{place}.py:1")
            for place in range(places)
            for n in range(places - place)
        ]
    )
    assert len(found) == LIMIT
    assert found[0].startswith(f"::error title={places} failed at p0.py")
    assert found[-1] == (
        "::error title=6 failed at 3 more places::"
        "3 at p9.py:1: E9%0A2 at p10.py:1: E10%0A1 at p11.py:1: E11"
    )
    assert len(commands([Failure(f"t{n}", "E", f"p{n}.py:1") for n in range(LIMIT)])) == LIMIT


def test_an_annotation_names_twenty_tests_and_counts_the_others() -> None:
    # [0015.20]
    found = commands([Failure(f"t{n}", "E", "x.py:1") for n in range(NAMED + 5)])
    (one,) = found
    lines = one.split("::", 2)[2].split("%0A")
    assert lines[:2] == ["t0: E", "t1: E"]
    assert lines[NAMED - 1] == f"t{NAMED - 1}: E"
    assert lines[NAMED:] == ["and 5 more"]
    (named,) = commands([Failure(f"t{n}", "E", "x.py:1") for n in range(NAMED)])
    assert named.split("::", 2)[2].split("%0A")[-1] == f"t{NAMED - 1}: E"


def test_an_error_is_cut_and_escaped() -> None:
    # [0015.20] a command is one line: its title has no colon or comma of its own
    long = "x" * (WIDE + 1)
    (one,) = commands([Failure("t", long, "x.py:1")])
    assert one.endswith("::t: " + "x" * (WIDE - 3) + "...")
    (fits,) = commands([Failure("t", "x" * WIDE, "x.py:1")])
    assert fits.endswith("::t: " + "x" * WIDE)
    (odd,) = commands([Failure("a,b", "50%\r", "x.py:1")])
    assert odd == "::error title=1 failed at x.py%3A1%3A 50%25%0D::a,b: 50%25%0D"
