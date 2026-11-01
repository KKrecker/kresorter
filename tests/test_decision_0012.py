"""Every item of decision 0012 is cited by a test (item 40).

A test cites an item as ``[0012.N]`` in a comment or docstring. This file fails on an item no
test cites unless it is still pending, on a citation of an item the decision does not have, and
on a pending item a test already cites. ``PENDING`` starts with every item and is empty when
step 5 closes: each commit that cites an item takes it out.
"""

import re
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "docs" / "decisions" / "0012-organize.md"
ITEM = re.compile(r"^(\d+)\. \*\*", re.MULTILINE)
CITATION = re.compile(r"\[0012\.(\d+)\]")

PENDING = frozenset({40})


def items() -> list[int]:
    return [int(number) for number in ITEM.findall(DECISION.read_text(encoding="utf-8"))]


def citing() -> Iterator[tuple[int, str]]:
    """Every citation in the tests: the item and the file that cites it."""
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if path.name != Path(__file__).name:
            for number in CITATION.findall(path.read_text(encoding="utf-8")):
                yield int(number), path.relative_to(ROOT).as_posix()


def test_the_items_are_numbered_in_order() -> None:
    numbers = items()
    assert numbers == list(range(1, len(numbers) + 1))


def test_every_item_is_cited_or_pending() -> None:
    cited = {number for number, _ in citing()}
    assert sorted(set(items()) - cited - PENDING) == []


def test_every_citation_is_of_an_item() -> None:
    assert sorted({(n, path) for n, path in citing() if n not in set(items())}) == []


def test_no_cited_item_is_still_pending() -> None:
    assert sorted({number for number, _ in citing()} & PENDING) == []


def test_every_pending_item_exists() -> None:
    assert sorted(PENDING - set(items())) == []
