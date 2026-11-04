"""The README, the changelog and the roadmap say what decision 0018 brought (items 22, 41-43).

The README's levels say what a cache is and why a browser's is for review; its window section
says the theme, the restart, Select all, the zones left out, the model's choice and
recommendation, grouping by meaning and what it sends, and the Local AI card, in the window's
own words; the changelog of 0.1.0 says the same for its users; the roadmap records the work
and the decision's accepted limitations, and its layout names every module of ``llm``. No Qt
is needed here.
"""

import json
import re
from pathlib import Path

from kresorter.llm.machine import RECOMMENDED
from kresorter.llm.settings import MODEL_VARIABLE
from kresorter.ui.settings import DEFAULTS, THEME_SETTINGS
from kresorter.ui.texts import CATALOG
from support.markdown import headings, section

ROOT = Path(__file__).resolve().parents[1]
DECISION = "docs/decisions/0018-owners-requests.md"
DONE = "Decision 0018: done (the owner's requests)"
LIMITS = "Accepted limitations of decision 0018"


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _said(name: str, title: str) -> str:
    """A section's text, its lines joined and each run of spaces one."""
    return " ".join(" ".join(section(_read(name), title)).split())


def _en(key: str) -> str:
    return CATALOG[key]["en"]


def _changelog() -> str:
    (title,) = [t for _, t, _ in headings(_read("CHANGELOG.md")) if t.startswith("[0.1.0]")]
    return _said("CHANGELOG.md", title)


def _entry(text: str, page: str) -> str:
    """The changelog's entry of the page named ``page``."""
    return text.split(f"The **{page}** page", 1)[1].split(" - ", 1)[0]


def _limitations() -> list[str]:
    """The titles of the decision's accepted limitations, as it writes them."""
    return re.findall(
        r"^- \*\*(.+?)\*\*",
        "\n".join(section(_read(DECISION), "Accepted limitations")),
        re.MULTILINE,
    )


# --- the README ---------------------------------------------------------------------------------


def test_the_levels_say_a_cache_is_likely_safe_and_a_browser_s_is_for_review() -> None:
    # [0018.22] And why, with the decision linked.
    text = _said("README.md", "Reports: `scan`, `analyze`")
    assert "A cache is `likely_safe`" in text
    assert "a browser's cache is `review`" in text
    assert "sign-ins" in text
    assert f"]({DECISION})" in text


def test_the_window_section_says_the_theme_and_the_restart() -> None:
    # [0018.41]
    text = _said("README.md", "Desktop app (optional)")
    appearance = _en("settings.appearance")
    themes = [_en(f"settings.theme_{theme}") for theme in THEME_SETTINGS]
    assert f"{appearance} ({', '.join(themes[:-1])} or {themes[-1]})" in text
    assert _en("settings.restart_action") in text


def test_the_window_section_says_select_all_and_the_zones_left_out() -> None:
    # [0018.41]
    text = _said("README.md", "Desktop app (optional)")
    assert f"{_en('quarantine.select_all')} and {_en('quarantine.clear')}" in text
    assert "left out" in text
    assert "put back" in text


def test_the_window_section_says_the_model_s_choice_and_recommendation() -> None:
    # [0018.41] The commands keep the variable; the window's choice is its own.
    text = _said("README.md", "Desktop app (optional)")
    assert all(f"`{model}`" in text for model in RECOMMENDED)
    assert f"`{MODEL_VARIABLE}`" in text
    assert "ollama pull" in text
    llm = _said("README.md", "AI explanations (optional)")
    assert "Settings page" in llm


def test_the_window_section_says_grouping_by_meaning_and_what_it_sends() -> None:
    # [0018.41]
    text = _said("README.md", "Desktop app (optional)")
    assert _en("organize.group") in text
    assert _en("organize.by_kind") in text
    grouping = text.split(_en("organize.group"), 1)[1]
    assert "names" in grouping
    assert "at most 100" in grouping
    assert "no path" in grouping


def test_the_window_section_says_the_local_ai_card() -> None:
    # [0018.41]
    text = _said("README.md", "Desktop app (optional)")
    overview = text.split("**Overview**", 1)[1].split("- **", 1)[0]
    assert _en("overview.ai_title") in overview


def test_the_window_section_shows_the_settings_file_as_it_is_written() -> None:
    # [0018.41] The defaults as save writes them; the model only once chosen.
    text = _said("README.md", "Desktop app (optional)")
    defaults = {
        "language": DEFAULTS.language,
        "include_machine": DEFAULTS.include_machine,
        "skipped_zones": list(DEFAULTS.skipped_zones),
        "theme": DEFAULTS.theme,
    }
    assert f"`{json.dumps(defaults)}`" in text
    assert "`model`" in text


# --- the changelog ------------------------------------------------------------------------------


def test_the_changelog_says_the_same_for_its_users() -> None:
    # [0018.42]
    text = _changelog()
    assert "a browser's cache `review`" in text
    assert _en("overview.ai_title") in _entry(text, _en("page.overview"))
    assert _en("organize.group") in _entry(text, _en("page.organize"))
    assert _en("quarantine.select_all") in _entry(text, _en("page.quarantine"))
    settings = _entry(text, _en("page.settings"))
    assert _en("settings.appearance") in settings
    assert _en("settings.restart_action") in settings
    assert "recommended" in settings


# --- the roadmap --------------------------------------------------------------------------------


def test_the_roadmap_records_the_work_and_the_accepted_limitations() -> None:
    # [0018.43]
    titles = [title for _, title, _ in headings(_read("docs/roadmap.md"))]
    assert titles.index(DONE) < titles.index(LIMITS) < titles.index("Left for later")
    done = _said("docs/roadmap.md", DONE)
    assert f"]({DECISION.removeprefix('docs/')})" in done
    assert "security-audit.md" in done
    limits = _said("docs/roadmap.md", LIMITS)
    assert _limitations()
    assert [title for title in _limitations() if title not in limits] == []


def test_the_layout_names_every_module_of_llm() -> None:
    # [0018.43] machine and group came with this decision.
    layout = _read("docs/roadmap.md").split("## Target package layout", 1)[1].splitlines()
    [start] = [index for index, line in enumerate(layout) if "── llm/" in line]
    end = next(index for index in range(start + 1, len(layout)) if "──" in layout[index])
    line = " ".join(layout[start:end])  # its comment, and the comment lines that continue it
    found = sorted(path.stem for path in (ROOT / "src" / "kresorter" / "llm").glob("*.py"))
    assert [name for name in found if not name.startswith("__") and name not in line] == []
