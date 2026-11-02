"""Every item of decision 0014 is cited by a test (item 43).

A test cites an item as ``[0014.N]`` in a comment or docstring. This file fails on an item no
test cites unless it is still pending, on a citation of an item the decision does not have, and
on a pending item a test already cites. ``PENDING`` starts with every item and is empty after
the last commit of the step 7 plan of 0014: the commit that completes an item takes it out.

The rules are checked on made-up items and citations first, so a wrong rule cannot pass in
silence; those checks are the tests of item 43, and this file is scanned like any other.
"""

import re
from collections.abc import Iterable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "docs" / "decisions" / "0014-ui.md"
ITEM = re.compile(r"^(\d+)\. \*\*", re.MULTILINE)
CITATION = re.compile(r"\[0014\.(\d+)\]")

# Taken out by the commit that completes each item (the step 7 plan of 0014).
COMPLETED: frozenset[int] = frozenset(
    {1, 7, 8, 9, 10, 11, 12, 28, 29, 30, 31, 32, 33, 34, 35, 36, 40, 43}
)
PENDING: frozenset[int] = frozenset(range(1, 44)) - COMPLETED


def numbered(text: str) -> list[int]:
    return [int(number) for number in ITEM.findall(text)]


def cited_in(text: str) -> list[int]:
    return [int(number) for number in CITATION.findall(text)]


def items() -> list[int]:
    return numbered(DECISION.read_text(encoding="utf-8"))


def citing() -> Iterator[tuple[int, str]]:
    """Every citation in the tests: the item and the file that cites it."""
    for path in sorted((ROOT / "tests").rglob("*.py")):
        for number in cited_in(path.read_text(encoding="utf-8")):
            yield number, path.relative_to(ROOT).as_posix()


def out_of_order(numbers: list[int]) -> bool:
    return numbers != list(range(1, len(numbers) + 1))


def uncovered(numbers: Iterable[int], cited: set[int], pending: frozenset[int]) -> list[int]:
    return sorted(set(numbers) - cited - pending)


def strays(numbers: Iterable[int], citations: Iterable[tuple[int, str]]) -> list[tuple[int, str]]:
    known = set(numbers)
    return sorted({(number, path) for number, path in citations if number not in known})


def stale(cited: set[int], pending: frozenset[int]) -> list[int]:
    return sorted(cited & pending)


def unknown(numbers: Iterable[int], pending: frozenset[int]) -> list[int]:
    return sorted(pending - set(numbers))


# --- the rules, on made-up items and citations [0014.43] -----------------------------------------


def cite(number: int) -> str:
    """A citation made at run time: written out here, it would cite a real item."""
    return "[0014." + str(number) + "]"


def test_items_are_bold_numbered_lines_and_citations_need_a_number() -> None:
    text = "1. **One.** text\n2. **Two.**\n   3. **indented, not an item**\n4. plain, not an item\n"
    assert numbered(text) == [1, 2]
    others = "[0014.N] [0012.4] 0014.5 (0014.6) " + CITATION.pattern
    assert cited_in(f"{cite(4)} {others} {cite(12)}") == [4, 12]


def test_a_gap_or_a_repeat_in_the_numbering_is_found() -> None:
    assert not out_of_order([1, 2, 3])
    assert out_of_order([1, 3])
    assert out_of_order([1, 2, 2])


def test_an_item_neither_cited_nor_pending_is_found() -> None:
    assert uncovered([1, 2, 3], {1}, frozenset({2})) == [3]
    assert uncovered([1, 2, 3], {1, 3}, frozenset({2})) == []


def test_a_citation_of_no_item_is_found_with_its_file() -> None:
    assert strays([1, 2], [(1, "a.py"), (7, "b.py"), (7, "b.py")]) == [(7, "b.py")]


def test_a_cited_item_still_pending_is_found() -> None:
    assert stale({1, 2}, frozenset({2, 3})) == [2]


def test_a_pending_item_the_decision_lacks_is_found() -> None:
    assert unknown([1, 2], frozenset({2, 9})) == [9]


# --- the rules, on decision 0014 and the tests ------------------------------------------------


def test_the_items_are_numbered_in_order() -> None:
    assert not out_of_order(items())


def test_every_item_is_cited_or_pending() -> None:
    assert uncovered(items(), {number for number, _ in citing()}, PENDING) == []


def test_every_citation_is_of_an_item() -> None:
    assert strays(items(), citing()) == []


def test_no_cited_item_is_still_pending() -> None:
    assert stale({number for number, _ in citing()}, PENDING) == []


def test_every_pending_item_exists() -> None:
    assert unknown(items(), PENDING) == []
