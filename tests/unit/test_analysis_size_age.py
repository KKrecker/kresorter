"""Large and old files (step 3, commit 3; decision 0010).

Pure: decides on scanned entries and an injected ``now_ns``; reads nothing from disk. Age is
``mtime_ns`` only (``atime`` is unreliable under ``noatime``/``relatime``), and an ``mtime`` in
the future is never "old". These findings are evidence for ``REVIEW`` only: on their own they
never propose anything for quarantine.
"""

from pathlib import Path

import pytest

from safeclean.analysis.size_age import (
    DAY_NS,
    SizeAgeFinding,
    SizeAgeReason,
    Thresholds,
    find_large_and_old,
)
from safeclean.core.models import FileEntry

MIB = 1024**2
NOW = 1_700_000_000_000_000_000
SMALL = Thresholds(large_bytes=100 * MIB, old_after_days=365)


def entry(path: Path, size: int = 1, age_days: float = 0) -> FileEntry:
    return FileEntry(path=path, size=size, mtime_ns=NOW - int(age_days * DAY_NS))


def run(entries: list[FileEntry], thresholds: Thresholds = SMALL) -> tuple[SizeAgeFinding, ...]:
    return find_large_and_old(entries, now_ns=NOW, thresholds=thresholds)


# --- large -------------------------------------------------------------------------------------


def test_a_file_at_the_size_threshold_is_large(tmp_path: Path) -> None:
    at = entry(tmp_path / "at.iso", size=100 * MIB)
    below = entry(tmp_path / "below.iso", size=100 * MIB - 1)

    findings = run([at, below])

    assert findings == (SizeAgeFinding(entry=at, reasons=(SizeAgeReason.LARGE,), age_days=0),)


# --- old ---------------------------------------------------------------------------------------


def test_a_file_unmodified_for_the_threshold_is_old(tmp_path: Path) -> None:
    at = entry(tmp_path / "at.txt", age_days=365)
    below = FileEntry(path=tmp_path / "below.txt", size=1, mtime_ns=NOW - 365 * DAY_NS + 1)

    findings = run([at, below])

    assert findings == (SizeAgeFinding(entry=at, reasons=(SizeAgeReason.OLD,), age_days=365),)


def test_age_is_reported_in_whole_days(tmp_path: Path) -> None:
    (finding,) = run([entry(tmp_path / "a.txt", age_days=400.9)])
    assert finding.age_days == 400


def test_an_mtime_in_the_future_is_never_old(tmp_path: Path) -> None:
    # Clock skew, a restored backup, a bad camera clock: no evidence of age at all.
    future = FileEntry(path=tmp_path / "f.txt", size=1, mtime_ns=NOW + 1000 * DAY_NS)
    assert run([future]) == ()


def test_an_mtime_in_the_future_reports_age_zero_when_large(tmp_path: Path) -> None:
    future = FileEntry(path=tmp_path / "f.iso", size=100 * MIB, mtime_ns=NOW + DAY_NS)
    (finding,) = run([future])
    assert finding.reasons == (SizeAgeReason.LARGE,)
    assert finding.age_days == 0


# --- both, order, defaults ---------------------------------------------------------------------


def test_large_and_old_lists_both_reasons_in_a_fixed_order(tmp_path: Path) -> None:
    both = entry(tmp_path / "old.iso", size=200 * MIB, age_days=1000)

    (finding,) = run([both])

    assert finding.reasons == (SizeAgeReason.LARGE, SizeAgeReason.OLD)


def test_findings_are_ordered_by_path(tmp_path: Path) -> None:
    b = entry(tmp_path / "b.iso", size=200 * MIB)
    a = entry(tmp_path / "a.iso", size=200 * MIB)
    assert [f.entry for f in run([b, a])] == [a, b]


def test_nothing_large_or_old_gives_no_findings(tmp_path: Path) -> None:
    assert run([entry(tmp_path / "a.txt"), entry(tmp_path / "b.txt", size=MIB, age_days=30)]) == ()


def test_default_thresholds() -> None:
    assert Thresholds() == Thresholds(large_bytes=500 * MIB, old_after_days=730)


@pytest.mark.parametrize("kwargs", [{"large_bytes": 0}, {"large_bytes": -1}, {"old_after_days": 0}])
def test_thresholds_must_be_positive(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="positive"):
        Thresholds(**kwargs)


def test_every_size_age_reason_has_a_case() -> None:
    assert {reason.value for reason in SizeAgeReason} == {"large", "old"}
