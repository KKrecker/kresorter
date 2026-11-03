"""Every item of decision 0012 is cited by a test (item 40).

A test cites an item as ``[0012.N]`` in a comment or docstring. This file fails on an item no
test cites unless it is still pending, on a citation of an item the decision does not have, and
on a pending item a test already cites, by the rules of ``support.decisions``. ``PENDING``
starts with every item and is empty when step 5 closes: each commit that cites an item takes it
out.
"""

from support.decisions import cited, citing, items, out_of_order, stale, strays, uncovered, unknown

DECISION = "0012"
PENDING: frozenset[int] = frozenset()


def test_the_items_are_numbered_in_order() -> None:
    assert not out_of_order(items(DECISION))


def test_every_item_is_cited_or_pending() -> None:
    assert uncovered(items(DECISION), cited(DECISION), PENDING) == []


def test_every_citation_is_of_an_item() -> None:
    assert strays(items(DECISION), citing(DECISION)) == []


def test_no_cited_item_is_still_pending() -> None:
    assert stale(cited(DECISION), PENDING) == []


def test_every_pending_item_exists() -> None:
    assert unknown(items(DECISION), PENDING) == []
