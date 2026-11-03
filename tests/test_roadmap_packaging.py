"""The roadmap records step 8 (decision 0015, item 30): a section ``Step 8: done (packaging)``
after the pre-step-8 audit and what step 7 carried into step 8, then the accepted limitations
it carries after it; the table says organize is refused on macOS only (decision 0017)."""

from pathlib import Path

from support.markdown import headings, section

ROOT = Path(__file__).resolve().parents[1]
DONE = "Step 8: done (packaging)"
CARRIED = "Accepted limitations carried after step 8"


def roadmap() -> str:
    return (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")


def test_the_roadmap_records_step_8_and_what_it_carries_after_it() -> None:
    # [0015.30]
    titles = [title for _, title, _ in headings(roadmap())]
    order = [
        "Step 7: done (ui)",
        "Step 8.0: done (pre-step-8 audit)",
        "Accepted limitations carried into step 8",
        DONE,
        CARRIED,
    ]
    assert [titles.index(title) for title in order] == sorted(titles.index(t) for t in order)
    done = " ".join(" ".join(section(roadmap(), DONE)).split())
    for words in ("Decision 0015", "decision 0016", "decision 0017", "100 %"):
        assert words in done, words
    limits = " ".join(" ".join(section(roadmap(), CARRIED)).split())
    for words in ("Everything from steps 2 to 7 still holds.", "Unsigned", "No macOS build"):
        assert words in limits, words


def test_the_table_says_organize_is_refused_on_macos_only() -> None:
    # [0015.30] organize on Windows since decision 0017
    (row,) = [line for line in roadmap().splitlines() if line.startswith("| 5 |")]
    assert "refused on macOS" in row
    assert "Windows at first" not in row
    (packaging,) = [line for line in roadmap().splitlines() if line.startswith("| 8 |")]
    assert "screenshots" in packaging
