"""Safety levels with their reasons (step 3, commit 4; decision 0010, items 11-13).

Three levels, no number: ``SAFE``, ``LIKELY_SAFE``, ``REVIEW``. Each piece of evidence has a
pinned level; a finding takes the level of its strongest evidence, and "large"/"old" never
raise it. Every reason is kept, strongest first, so a ``REVIEW`` finding still shows the user
why it is in the report. Only ``SAFE`` and ``LIKELY_SAFE`` are proposed for quarantine.
"""

import itertools
from pathlib import Path

import pytest

from kresorter.analysis.duplicates import DuplicateDecision, KeepReason
from kresorter.analysis.score import (
    Assessment,
    Evidence,
    Level,
    Reason,
    assess,
    duplicate_reason,
    junk_reason,
    level_of,
    size_age_reasons,
)
from kresorter.analysis.size_age import SizeAgeFinding, SizeAgeReason
from kresorter.core.heuristics import JunkCategory, JunkMatch
from kresorter.core.models import FileEntry
from kresorter.core.preflight import Candidate

MIB = 1024**2

# --- the pinned table --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("evidence", "level"),
    [
        (Evidence.JUNK_CACHE, Level.SAFE),
        (Evidence.JUNK_THUMBNAILS, Level.SAFE),
        (Evidence.JUNK_OS_METADATA, Level.SAFE),
        (Evidence.JUNK_TEMP, Level.LIKELY_SAFE),
        (Evidence.JUNK_CRASH_DUMP, Level.LIKELY_SAFE),
        (Evidence.DUPLICATE_COPY, Level.LIKELY_SAFE),
        (Evidence.LARGE, Level.REVIEW),
        (Evidence.OLD, Level.REVIEW),
    ],
)
def test_each_evidence_has_its_pinned_level(evidence: Evidence, level: Level) -> None:
    assert level_of(evidence) is level


def test_the_evidence_set_is_pinned() -> None:
    # A new kind of evidence needs a decision record and a row in the table above.
    assert [e.value for e in Evidence] == [
        "junk_cache",
        "junk_thumbnails",
        "junk_os_metadata",
        "junk_temp",
        "junk_crash_dump",
        "duplicate_copy",
        "large",
        "old",
    ]


def test_the_levels_are_pinned_strongest_first() -> None:
    assert [level.value for level in Level] == ["safe", "likely_safe", "review"]


def test_every_junk_category_has_evidence(tmp_path: Path) -> None:
    # A new junk category must not slip through unscored.
    for category in JunkCategory:
        match = JunkMatch(tmp_path / "f", "rule", category, "why")
        assert junk_reason(match).evidence.value == f"junk_{category.value}"


# --- reasons from findings ---------------------------------------------------------------------


def test_junk_reason_names_the_rule(tmp_path: Path) -> None:
    match = JunkMatch(tmp_path / "m.pyc", "python-bytecode", JunkCategory.CACHE, "Bytecode")
    assert junk_reason(match) == Reason(Evidence.JUNK_CACHE, "python-bytecode")


def test_duplicate_reason_names_the_copy_that_stays(tmp_path: Path) -> None:
    keep = FileEntry(path=tmp_path / "keep" / "a.bin", size=10, mtime_ns=1)
    copy = FileEntry(path=tmp_path / "Downloads" / "a.bin", size=10, mtime_ns=2)
    decision = DuplicateDecision(
        digest="d",
        keep=keep,
        reason=KeepReason.OUTSIDE_SAFE_ZONE,
        remove=(Candidate(entry=copy, twin=keep, digest="d"),),
    )

    assert duplicate_reason(decision) == Reason(Evidence.DUPLICATE_COPY, str(keep.path))


def test_size_age_reasons_keep_every_reason_with_details(tmp_path: Path) -> None:
    entry = FileEntry(path=tmp_path / "old.iso", size=600 * MIB, mtime_ns=1)
    finding = SizeAgeFinding(entry, (SizeAgeReason.LARGE, SizeAgeReason.OLD), age_days=1000)

    assert size_age_reasons(finding) == (
        Reason(Evidence.LARGE, "600.0 MiB"),
        Reason(Evidence.OLD, "unmodified for 1000 days"),
    )


# --- combining ---------------------------------------------------------------------------------

CACHE = Reason(Evidence.JUNK_CACHE, "python-bytecode")
TEMP = Reason(Evidence.JUNK_TEMP, "posix-temp")
COPY = Reason(Evidence.DUPLICATE_COPY, "/home/u/keep/a.bin")
LARGE = Reason(Evidence.LARGE, "600.0 MiB")
OLD = Reason(Evidence.OLD, "unmodified for 1000 days")


def test_the_strongest_evidence_sets_the_level() -> None:
    assert assess([COPY, CACHE]).level is Level.SAFE


def test_large_and_old_never_raise_a_level() -> None:
    assert assess([TEMP, LARGE, OLD]).level is Level.LIKELY_SAFE


def test_large_and_old_alone_are_review_with_every_reason() -> None:
    assessment = assess([OLD, LARGE])
    assert assessment == Assessment(Level.REVIEW, (LARGE, OLD))
    assert assessment.proposed is False


@pytest.mark.parametrize("reason", [CACHE, TEMP, COPY])
def test_safe_and_likely_safe_are_proposed(reason: Reason) -> None:
    assert assess([reason]).proposed is True


def test_reasons_are_kept_strongest_first_in_evidence_order() -> None:
    assert assess([OLD, COPY, LARGE, TEMP, CACHE]).reasons == (CACHE, TEMP, COPY, LARGE, OLD)


def test_the_assessment_does_not_depend_on_input_order() -> None:
    results = {assess(list(order)) for order in itertools.permutations([CACHE, TEMP, COPY, OLD])}
    assert len(results) == 1


def test_the_same_reason_twice_is_kept_once() -> None:
    assert assess([TEMP, TEMP]).reasons == (TEMP,)


def test_an_assessment_needs_evidence() -> None:
    with pytest.raises(ValueError, match="evidence"):
        assess([])
