"""The README, in both languages, the changelog and the roadmap say what decision 0020 brought
(items 16 and 20-23).

The README says how grouping works now (batches, numbers, the context, no thinking), the kinds
added, the sessions never touched, the programs' caches, what is left to Windows and why, and
what a scan spends its time on, with the line the Findings page shows; ``README.ru.md`` says it
in Russian, in the window's own words. No source reads a volume (item 20). The changelog of
0.1.0 says the same for its users; the roadmap records the work and the decision's accepted
limitations, and its layout names every module of ``core``. No Qt is needed here.
"""

import re
from pathlib import Path

import pytest

from kresorter.core.policy import BlockReason
from kresorter.core.scanner import ScanTimes
from kresorter.organize.categories import default_table
from kresorter.ui.i18n import Language, Translator
from kresorter.ui.texts import CATALOG
from support.markdown import headings, section

ROOT = Path(__file__).resolve().parents[1]
DECISION = "docs/decisions/0020-owners-requests-3.md"
DONE = "Decision 0020: done (the owner's requests, third round)"
LIMITS = "Accepted limitations of decision 0020"
READMES: list[tuple[str, Language]] = [("README.md", "en"), ("README.ru.md", "ru")]
REPORTS = "Reports: `scan`, `analyze`"
ORGANIZE = "Organize"
AI = "AI explanations (optional)"
DESKTOP = "Desktop app (optional)"
LEFT_TO_WINDOWS = (
    r"`SoftwareDistribution\Download`",
    "`Prefetch`",
    "`WinSxS`",
    "`Windows.old`",
    "`hiberfil.sys`",
    "`pagefile.sys`",
)
SESSIONS = ("`Local State`", "`Cookies`", "`Login Data`", "`tdata`", "`.ssh`", "`sessions.toml`")
WINDOWS_CLEANS = {
    "en": ("Settings > System > Storage > Temporary files", "Disk Cleanup"),
    "ru": ("Параметры > Система > Память > Временные файлы", "Очистка диска"),
}


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _said(name: str, title: str) -> str:
    """The section of ``name`` at the place where README.md has the heading ``title``, its
    lines joined and each run of spaces one."""
    english = [heading for _, heading, _ in headings(_read("README.md"))]
    theirs = [heading for _, heading, _ in headings(_read(name))]
    lines = section(_read(name), theirs[english.index(title)])
    return " ".join(" ".join(lines).split())


def _page(text: str, page: str) -> str:
    """The bullet of the window's page named ``page``."""
    return text.split(f"- **{page}**", 1)[1].split(" - **", 1)[0]


def _changelog() -> str:
    (title,) = [t for _, t, _ in headings(_read("CHANGELOG.md")) if t.startswith("[0.1.0]")]
    return " ".join(" ".join(section(_read("CHANGELOG.md"), title)).split())


def _limitations() -> list[str]:
    """The titles of the decision's accepted limitations, as it writes them."""
    return re.findall(
        r"^- \*\*(.+?)\*\*",
        "\n".join(section(_read(DECISION), "Accepted limitations")),
        re.MULTILINE,
    )


# --- the README, in both languages ---------------------------------------------------------------


@pytest.mark.parametrize(("name", "language"), READMES)
def test_grouping_is_said_in_batches_of_numbered_names(name: str, language: Language) -> None:
    # [0020.21] at most 40 names a batch, 10 batches, 400 names; the note
    organize = _page(_said(name, DESKTOP), CATALOG["page.organize"][language])
    if language == "en":
        said = ("at most 400", "batches of at most 40", "numbered", "at most 24")
    else:
        said = ("не более 400", "пакетами не более чем по 40", "под номерами", "не более 24")
    assert [words for words in said if words not in organize] == []
    note = CATALOG["organize.grouped_stopped"][language].split("(", 1)[0]
    assert note in organize


@pytest.mark.parametrize(("name", "language"), READMES)
def test_the_context_and_the_answer_s_shape_are_said(name: str, language: Language) -> None:
    # [0020.21] the recommended models are said on the Settings page (decision 0019)
    text = _said(name, AI)
    for words in ("4096", '`"think": false`', "`/no_think`", "`format`", "`response_format`"):
        assert words in text, words
    assert ("the answer was cut at its length" if language == "en" else "обрезан") in text


@pytest.mark.parametrize(("name", "language"), READMES)
def test_the_kinds_added(name: str, language: Language) -> None:
    # [0020.21] every category, as its directory is named; in the window in its language
    text = _said(name, ORGANIZE)
    assert [n for n in default_table().names if f"`{n}`" not in text] == []
    organize = _page(_said(name, DESKTOP), CATALOG["page.organize"][language])
    shown = [Translator(language).category(n) for n in ("Torrents", "Fonts", "3D models")]
    assert [n for n in shown if n not in organize] == []
    assert "`movie.srt`" not in text  # a film and its subtitles now go together


@pytest.mark.parametrize(("name", "language"), READMES)
def test_the_sessions_are_never_touched(name: str, language: Language) -> None:
    # [0020.21]
    text = _said(name, REPORTS)
    assert Translator(language).label(BlockReason.SESSION) in text
    assert [words for words in SESSIONS if words not in text] == []


@pytest.mark.parametrize(("name", "language"), READMES)
def test_the_programs_caches_are_a_zone_on_windows(name: str, language: Language) -> None:
    # [0020.21]
    overview = _page(_said(name, DESKTOP), CATALOG["page.overview"][language])
    assert CATALOG["overview.caches"][language] in overview
    assert "`caches`" in _said(name, DESKTOP)


@pytest.mark.parametrize(("name", "language"), READMES)
def test_what_is_left_to_windows_and_why(name: str, language: Language) -> None:
    # [0020.21] [0020.16]
    text = _said(name, REPORTS)
    assert [words for words in LEFT_TO_WINDOWS if words not in text] == []
    assert [words for words in WINDOWS_CLEANS[language] if words not in text] == []
    assert "Prefetch" in text.split("`Prefetch`", 1)[1]  # said again: not to be cleaned


@pytest.mark.parametrize(("name", "language"), READMES)
def test_what_a_scan_spends_its_time_on(name: str, language: Language) -> None:
    # [0020.21] [0020.20] and the line the Findings page shows
    text = _said(name, REPORTS)
    assert "MFT" in text
    assert "WizTree" in text
    translator = Translator(language)
    times = ScanTimes(total=9.8, listing=2.1, open_checks=0.4, duplicates=7.3)
    line = translator.text(
        "findings.took",
        total=translator.seconds(times.total),
        listing=translator.seconds(times.listing),
        checks=translator.seconds(times.open_checks),
        duplicates=translator.seconds(times.duplicates),
    )
    assert line in _page(_said(name, DESKTOP), CATALOG["page.findings"][language])


def test_no_source_reads_a_volume() -> None:
    # [0020.20] no device path, no file system control code
    sources = sorted((ROOT / "src" / "kresorter").rglob("*.py"))
    found = [
        path.name
        for path in sources
        if re.search(r"FSCTL_|\\\\\.\\|\$MFT", path.read_text(encoding="utf-8"))
    ]
    assert found == []


# --- the changelog -----------------------------------------------------------------------------


def test_the_changelog_says_the_same_for_its_users() -> None:
    # [0020.22]
    text = _changelog()
    for words in (
        "batches",
        "Qwen3",
        "`Torrents`",
        "`Fonts`",
        "`3D models`",
        CATALOG["overview.caches"]["en"],
        "Sign-ins and sessions",
        "`Windows.old`",
        "Scanned in",
        "only the junk and the copies",
    ):
        assert words in text, words


# --- the roadmap --------------------------------------------------------------------------------


def test_the_roadmap_records_the_work_and_the_accepted_limitations() -> None:
    # [0020.23]
    roadmap = "docs/roadmap.md"
    titles = [title for _, title, _ in headings(_read(roadmap))]
    assert titles.index(DONE) < titles.index(LIMITS) < titles.index("Left for later")
    done = " ".join(" ".join(section(_read(roadmap), DONE)).split())
    assert f"]({DECISION.removeprefix('docs/')})" in done
    for words in ("batches", "Qwen3", "`core/sessions.toml`", "`caches`", "MFT", "digests"):
        assert words in done, words
    limits = " ".join(" ".join(section(_read(roadmap), LIMITS)).split())
    assert len(_limitations()) == 7
    assert [title for title in _limitations() if title not in limits] == []


def test_the_layout_names_every_module_of_core() -> None:
    # [0020.23] sessions came with this decision.
    layout = _read("docs/roadmap.md").split("## Target package layout", 1)[1].splitlines()
    [start] = [index for index, line in enumerate(layout) if "── core/" in line]
    end = next((i for i in range(start + 1, len(layout)) if "──" in layout[i]), len(layout))
    line = " ".join(layout[start:end])
    found = sorted(
        path.stem
        for path in (ROOT / "src" / "kresorter" / "core").iterdir()
        if path.suffix == ".py" or (path.is_dir() and (path / "__init__.py").exists())
    )
    assert [name for name in found if not name.startswith("__") and name not in line] == []
