"""Duplicate groups -> which copy stays, which copies become quarantine candidates (step 3).

Pure decision on scanned entries; nothing is read from disk. The keeper is chosen by a fixed
order of criteria, each one explainable to the user:

1. a copy that no junk rule matches beats one that does (a cache copy is the expendable one);
2. a copy outside the safe zones (``~/Downloads``, ``~/.cache``) beats one inside them;
3. the oldest ``mtime_ns`` (most likely the original);
4. the shallowest path;
5. the first path in sort order (only so the result is deterministic).

Every other copy becomes a ``Candidate`` with the keeper as its twin and the group digest, so
preflight re-checks the keeper right before anything moves. A group never loses all copies.
"""

import itertools
from pathlib import Path

import pytest

from fakes import FakeOpenFiles, make_policy
from safeclean.analysis.duplicates import DuplicateDecision, KeepReason, decide
from safeclean.core.heuristics import JunkClassifier, load_rules
from safeclean.core.models import FileEntry
from safeclean.core.preflight import Candidate
from safeclean.core.scanner import ScanContext, scan

DIGEST = "ab" * 32
SIZE = 4096
T0 = 1_600_000_000_000_000_000

RULES = '[[rule]]\nid = "cachedir"\ncategory = "cache"\ndescription = "x"\ndirs = ["cache"]\n'
CLASSIFIER = JunkClassifier(load_rules(RULES), platform="linux")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def zones(home: Path) -> tuple[Path, ...]:
    return (home / "Downloads", home / ".cache")


def copy(path: Path, mtime_ns: int = T0) -> FileEntry:
    return FileEntry(path=path, size=SIZE, mtime_ns=mtime_ns)


def run(copies: list[FileEntry], zones: tuple[Path, ...]) -> DuplicateDecision:
    return decide(DIGEST, copies, classifier=CLASSIFIER, safe_zones=zones)


# --- shape of the decision ---------------------------------------------------------------------


def test_every_other_copy_becomes_a_candidate_twinned_with_the_keeper(
    home: Path, zones: tuple[Path, ...]
) -> None:
    keeper = copy(home / "Photos" / "a.jpg", T0)
    second = copy(home / "Backup" / "a.jpg", T0 + 1)
    third = copy(home / "Backup" / "old" / "a.jpg", T0 + 2)

    decision = run([third, keeper, second], zones)

    assert decision.digest == DIGEST
    assert decision.keep == keeper
    assert decision.remove == (
        Candidate(entry=second, twin=keeper, digest=DIGEST),
        Candidate(entry=third, twin=keeper, digest=DIGEST),
    )
    assert decision.wasted_bytes == 2 * SIZE


def test_the_keeper_is_never_a_candidate(home: Path, zones: tuple[Path, ...]) -> None:
    copies = [copy(home / "x" / f"{i}.bin", T0 + i) for i in range(5)]
    decision = run(copies, zones)
    assert decision.keep not in [c.entry for c in decision.remove]
    assert len(decision.remove) == 4


# --- criteria, in order ------------------------------------------------------------------------


def test_a_copy_no_junk_rule_matches_is_kept(home: Path, zones: tuple[Path, ...]) -> None:
    cached = copy(home / "cache" / "a.bin", T0)  # older, but in a junk location
    real = copy(home / "work" / "a.bin", T0 + 10)

    decision = run([cached, real], zones)

    assert decision.keep == real
    assert decision.reason is KeepReason.NOT_JUNK


def test_a_copy_outside_the_safe_zones_is_kept(home: Path, zones: tuple[Path, ...]) -> None:
    downloaded = copy(home / "Downloads" / "a.pdf", T0)
    filed = copy(home / "Documents" / "taxes" / "a.pdf", T0 + 10)

    decision = run([downloaded, filed], zones)

    assert decision.keep == filed
    assert decision.reason is KeepReason.OUTSIDE_SAFE_ZONE


def test_the_oldest_copy_is_kept(home: Path, zones: tuple[Path, ...]) -> None:
    newer = copy(home / "a" / "f.bin", T0 + 5)
    older = copy(home / "b" / "f.bin", T0)

    decision = run([newer, older], zones)

    assert decision.keep == older
    assert decision.reason is KeepReason.OLDEST


def test_the_shallowest_copy_is_kept(home: Path, zones: tuple[Path, ...]) -> None:
    deep = copy(home / "a" / "b" / "c" / "f.bin")
    shallow = copy(home / "z" / "f.bin")

    decision = run([deep, shallow], zones)

    assert decision.keep == shallow
    assert decision.reason is KeepReason.SHALLOWEST


def test_ties_are_broken_by_path_order(home: Path, zones: tuple[Path, ...]) -> None:
    b = copy(home / "b" / "f.bin")
    a = copy(home / "a" / "f.bin")

    decision = run([b, a], zones)

    assert decision.keep == a
    assert decision.reason is KeepReason.FIRST_BY_PATH


def test_junk_outranks_safe_zone_and_age(home: Path, zones: tuple[Path, ...]) -> None:
    # In Downloads and newer, but not junk: still beats the old cache copy.
    cached = copy(home / "work" / "cache" / "a.bin", T0)
    downloaded = copy(home / "Downloads" / "a.bin", T0 + 10)

    decision = run([cached, downloaded], zones)

    assert decision.keep == downloaded
    assert decision.reason is KeepReason.NOT_JUNK


def test_the_reason_is_what_beat_the_runner_up(home: Path, zones: tuple[Path, ...]) -> None:
    # Both non-junk copies are outside the zones; the junk one is irrelevant to the reason.
    a = copy(home / "a" / "f.bin", T0)
    b = copy(home / "b" / "f.bin", T0 + 1)
    junk = copy(home / "cache" / "f.bin", T0 - 1)

    decision = run([junk, b, a], zones)

    assert decision.keep == a
    assert decision.reason is KeepReason.OLDEST


def test_when_every_copy_is_junk_one_still_stays(home: Path, zones: tuple[Path, ...]) -> None:
    copies = [copy(home / "cache" / f"{i}.bin", T0 + i) for i in range(3)]

    decision = run(copies, zones)

    assert decision.keep == copies[0]
    assert len(decision.remove) == 2


def test_the_decision_does_not_depend_on_input_order(home: Path, zones: tuple[Path, ...]) -> None:
    copies = [
        copy(home / "Downloads" / "f.bin", T0),
        copy(home / "cache" / "f.bin", T0),
        copy(home / "b" / "f.bin", T0 + 1),
        copy(home / "a" / "deep" / "f.bin", T0 + 1),
    ]
    decisions = {run(list(order), zones) for order in itertools.permutations(copies)}
    assert len(decisions) == 1


def test_every_keep_reason_has_a_case() -> None:
    assert {reason.value for reason in KeepReason} == {
        "not_junk",
        "outside_safe_zone",
        "oldest",
        "shallowest",
        "first_by_path",
    }


# --- invalid groups are programming errors -----------------------------------------------------


def test_a_single_copy_is_not_a_group(home: Path, zones: tuple[Path, ...]) -> None:
    with pytest.raises(ValueError, match="at least two"):
        run([copy(home / "a.bin")], zones)


def test_copies_of_different_sizes_are_not_a_group(home: Path, zones: tuple[Path, ...]) -> None:
    other = FileEntry(path=home / "b.bin", size=SIZE + 1, mtime_ns=T0)
    with pytest.raises(ValueError, match="size"):
        run([copy(home / "a.bin"), other], zones)


def test_the_same_path_twice_is_not_a_group(home: Path, zones: tuple[Path, ...]) -> None:
    with pytest.raises(ValueError, match="twice"):
        run([copy(home / "a.bin"), copy(home / "a.bin", T0 + 1)], zones)


# --- fed by a real scan ------------------------------------------------------------------------


def test_a_scanned_group_feeds_the_decision(tmp_path: Path) -> None:
    root = tmp_path / "root"
    for name in ("keep/a.bin", "Downloads/a.bin"):
        (root / name).parent.mkdir(parents=True)
        (root / name).write_bytes(b"same bytes")
    context = ScanContext(
        policy=make_policy(tmp_path),
        open_files=FakeOpenFiles(),
        classifier=CLASSIFIER,
        open_files_checked=True,
        platform="linux",
    )
    (group,) = scan([root], context).duplicates

    decision = decide(
        group.digest, group.entries, classifier=CLASSIFIER, safe_zones=[root / "Downloads"]
    )

    assert decision.keep.path == root / "keep" / "a.bin"
    assert [c.entry.path for c in decision.remove] == [root / "Downloads" / "a.bin"]
    assert decision.remove[0].twin in group.entries
