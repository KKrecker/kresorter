"""The rules of a decision's meta-test: every item is cited by a test (0012 item 40, 0013
item 28, 0014 item 43).

A test cites item N of decision D as ``[D.N]`` in a comment or docstring. A meta-test fails on
an item no test cites unless it is still pending, on a citation of an item the decision does not
have, and on a pending item a test already cites. The citations here are made at run time, so
this file, scanned like any other, cites nothing.
"""

import re
from collections.abc import Iterable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ITEM = re.compile(r"^(\d+)\. \*\*", re.MULTILINE)


def citation(decision: str) -> re.Pattern[str]:
    return re.compile(r"\[" + decision + r"\.(\d+)\]")


def cite(decision: str, number: int) -> str:
    return "[" + decision + "." + str(number) + "]"


def numbered(text: str) -> list[int]:
    return [int(number) for number in ITEM.findall(text)]


def cited_in(text: str, decision: str) -> list[int]:
    return [int(number) for number in citation(decision).findall(text)]


def items(decision: str) -> list[int]:
    """The items of the decision numbered ``decision``, as its file numbers them."""
    (path,) = (ROOT / "docs" / "decisions").glob(f"{decision}-*.md")
    return numbered(path.read_text(encoding="utf-8"))


def citing(decision: str) -> Iterator[tuple[int, str]]:
    """Every citation of the decision in the tests: the item and the file that cites it."""
    for path in sorted((ROOT / "tests").rglob("*.py")):
        for number in cited_in(path.read_text(encoding="utf-8"), decision):
            yield number, path.relative_to(ROOT).as_posix()


def cited(decision: str) -> set[int]:
    return {number for number, _ in citing(decision)}


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


STRAYS = [(1, "a.py"), (7, "b.py"), (7, "b.py")]


def wrong_rules(decision: str) -> list[str]:
    """The rules that fail on made-up items and citations of ``decision``: none, unless a rule is
    wrong, which would otherwise pass in silence."""
    text = "1. **One.** text\n2. **Two.**\n   3. **indented, not an item**\n4. plain, not an item\n"
    others = f"[{decision}.N] {cite('0000', 4)} {decision}.5 ({decision}.6) "
    made_up = f"{cite(decision, 4)} {others}{citation(decision).pattern} {cite(decision, 12)}"
    checks: list[tuple[str, object, object]] = [
        ("items are bold numbered lines", numbered(text), [1, 2]),
        ("a citation needs the decision and a number", cited_in(made_up, decision), [4, 12]),
        ("items in order", out_of_order([1, 2, 3]), False),
        ("a gap in the numbering", out_of_order([1, 3]), True),
        ("a repeat in the numbering", out_of_order([1, 2, 2]), True),
        ("an item neither cited nor pending", uncovered([1, 2, 3], {1}, frozenset({2})), [3]),
        ("every item cited or pending", uncovered([1, 2, 3], {1, 3}, frozenset({2})), []),
        ("a citation of no item, with its file", strays([1, 2], STRAYS), [(7, "b.py")]),
        ("a cited item still pending", stale({1, 2}, frozenset({2, 3})), [2]),
        ("a pending item the decision lacks", unknown([1, 2], frozenset({2, 9})), [9]),
    ]
    return [rule for rule, found, expected in checks if found != expected]
