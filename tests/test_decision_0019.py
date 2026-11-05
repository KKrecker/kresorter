"""Every item of decision 0019 is cited by a test (item 24).

A test cites an item as ``[0019.N]`` in a comment or docstring. This file fails on an item no
test cites unless it is still pending, on a citation of an item the decision does not have, and
on a pending item a test already cites. ``PENDING`` starts with every item and is empty after
the last commit of the plan of 0019: the commit that completes an item takes it out.

The rules, those of ``support.decisions``, are checked on made-up items and citations first, so
a wrong rule cannot pass in silence; that check is the test of item 24, and this file is
scanned like any other.
"""

from support.decisions import (
    cited,
    citing,
    items,
    out_of_order,
    stale,
    strays,
    uncovered,
    unknown,
    wrong_rules,
)

DECISION = "0019"
# Taken out by the commit that completes each item (the plan of 0019).
COMPLETED: frozenset[int] = frozenset({1, 2, 24})
PENDING: frozenset[int] = frozenset(range(1, 25)) - COMPLETED


def test_the_rules_hold_on_made_up_items_and_citations() -> None:
    # [0019.24]
    assert wrong_rules(DECISION) == []


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
