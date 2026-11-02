"""The roadmap records step 7 and its accepted limitations, and the target layout names the
modules of ``safeclean.ui`` (decision 0014, item 42)."""

import re
from pathlib import Path

from support.markdown import headings, section

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs" / "roadmap.md"
LAYOUT = "Target package layout"


def roadmap() -> str:
    return ROADMAP.read_text(encoding="utf-8")


def modules() -> list[str]:
    """The modules of ``safeclean.ui``, but its package and its ``__main__``."""
    found = sorted(path.stem for path in (ROOT / "src" / "safeclean" / "ui").glob("*.py"))
    return [name for name in found if not name.startswith("__")]


def test_the_roadmap_records_step_7_and_what_it_carries_into_step_8() -> None:
    # [0014.42]
    titles = [title for _, title, _ in headings(roadmap())]
    assert "Step 7: done (ui)" in titles
    assert "Accepted limitations carried into step 8" in titles
    assert titles.index("Step 7: done (ui)") < titles.index(
        "Accepted limitations carried into step 8"
    )
    done = " ".join(section(roadmap(), "Step 7: done (ui)"))
    assert "Decision 0014" in done
    limits = " ".join(section(roadmap(), "Accepted limitations carried into step 8"))
    assert "Everything from steps 2 to 6 still holds." in limits


def ui_entry(layout: list[str]) -> str:
    """The comment of the layout's ``ui/`` line and of the comment lines that continue it."""
    [start] = [index for index, line in enumerate(layout) if "── ui/" in line]
    lines = [layout[start]]
    for line in layout[start + 1 :]:
        if not line.lstrip().startswith("#"):
            break
        lines.append(line)
    return " ".join(line.split("#", 1)[1] for line in lines)


def test_the_target_layout_names_every_module_of_the_window() -> None:
    # [0014.42] Beside ui/ in the layout, each module's name as a word.
    entry = ui_entry(section(roadmap(), LAYOUT))
    named = set(re.findall(r"[a-z_][a-z0-9_]*", entry))
    assert "step 7" in entry
    assert [name for name in modules() if name not in named] == []
    assert {"window", "settings_page"} <= set(modules())
