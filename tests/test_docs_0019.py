"""The README, in both languages, the changelog and the roadmap say what decision 0019 brought
(items 21-23).

The README says the answers' language; LM Studio, its settings, its steps as ``kresorter llm
status`` prints them, the two requests it is asked and that it is sent the same facts; the
server's choice in the window, in the window's own words; the release's files; and the licence.
``README.ru.md`` says it in Russian, with the same names, variables and code: a section of it is
the one at the place of README.md's. The changelog of 0.1.0 says the same for its users; the
roadmap records the work and the decision's accepted limitations, and its layout names every
module of ``llm`` and ``ui``. No Qt is needed here.
"""

import io
import re
import socket
from pathlib import Path

import pytest

from kresorter import __version__, cli
from kresorter.cli_llm import AGAIN, LMSTUDIO_INSTALL, LMSTUDIO_SETTINGS
from kresorter.environment import Environment
from kresorter.llm.machine import LMSTUDIO_RECOMMENDED, RECOMMENDED
from kresorter.llm.settings import (
    LMSTUDIO_ADDRESS,
    LMSTUDIO_MODEL_VARIABLE,
    LMSTUDIO_URL_VARIABLE,
    MODEL_VARIABLE,
    SERVER_VARIABLE,
    URL_VARIABLE,
)
from kresorter.ui.texts import CATALOG
from support.markdown import blocks, headings, section

ROOT = Path(__file__).resolve().parents[1]
DECISION = "docs/decisions/0019-owners-requests-2.md"
DONE = "Decision 0019: done (the owner's requests, second round)"
LIMITS = "Accepted limitations of decision 0019"
READMES = [("README.md", "en"), ("README.ru.md", "ru")]
AI = "AI explanations (optional)"
DESKTOP = "Desktop app (optional)"
WHEEL = "kresorter-<version>-py3-none-any.whl"
SDIST = "kresorter-<version>.tar.gz"
VARIABLES = (
    SERVER_VARIABLE,
    URL_VARIABLE,
    MODEL_VARIABLE,
    LMSTUDIO_URL_VARIABLE,
    LMSTUDIO_MODEL_VARIABLE,
)


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _lines(name: str, title: str) -> list[str]:
    """The section of ``name`` at the place where README.md has the heading ``title``."""
    english = [heading for _, heading, _ in headings(_read("README.md"))]
    theirs = [heading for _, heading, _ in headings(_read(name))]
    return section(_read(name), theirs[english.index(title)])


def _said(name: str, title: str) -> str:
    """That section's text, its lines joined and each run of spaces one."""
    return " ".join(" ".join(_lines(name, title)).split())


def _status() -> list[str]:
    """What ``kresorter llm status`` prints for LM Studio when nothing listens at its address."""
    with socket.create_server(("127.0.0.1", 0)) as taken:
        url = f"http://127.0.0.1:{taken.getsockname()[1]}"
    out, err = io.StringIO(), io.StringIO()
    env = {SERVER_VARIABLE: "lmstudio", LMSTUDIO_URL_VARIABLE: url}
    code = cli.main(["llm", "status"], out=out, err=err, environment=Environment(llm_env=env))
    assert (code, err.getvalue()) == (1, "")
    return out.getvalue().splitlines()


def _changelog() -> str:
    (title,) = [t for _, t, _ in headings(_read("CHANGELOG.md")) if t.startswith("[0.1.0]")]
    return " ".join(" ".join(section(_read("CHANGELOG.md"), title)).split())


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


# --- the README, in both languages ---------------------------------------------------------------


def test_a_section_of_the_russian_readme_is_the_one_at_the_same_place() -> None:
    # [0019.21] how this file reads README.ru.md
    assert _lines("README.ru.md", "Linux") == section(_read("README.ru.md"), "Linux")
    assert _lines("README.ru.md", AI)[0] == _lines("README.md", AI)[0] == ""
    assert blocks(_lines("README.ru.md", AI), "text") == blocks(_lines("README.md", AI), "text")


def test_the_answers_are_in_the_window_s_language_and_in_english_on_the_console() -> None:
    # [0019.21]
    english = _said("README.md", AI)
    assert "in the window's language, English or Russian" in english
    assert "in English on the console" in english
    russian = _said("README.ru.md", AI)
    assert "на языке окна, английском или русском" in russian
    assert "на английском в консоли" in russian


@pytest.mark.parametrize(("name", "language"), READMES)
def test_lm_studio_and_its_settings(name: str, language: str) -> None:
    # [0019.21] the server, LM Studio's address and model, its first chat model by default
    text = _said(name, AI)
    assert "[LM Studio](https://lmstudio.ai)" in text
    assert [variable for variable in VARIABLES if f"`{variable}`" not in text] == []
    assert "`ollama`" in text
    assert "`lmstudio`" in text
    assert f"`{LMSTUDIO_ADDRESS.url}`" in text
    assert "`embed`" in text
    assert "LM Studio" in _said(name, "Safety principles")


def test_lm_studio_s_steps_are_those_llm_status_prints() -> None:
    # [0019.21] README.ru.md has the same code blocks (tests/test_readme_ru.py)
    shown = [
        block for block in blocks(_lines("README.md", AI), "text") if "LM Studio: " in block[0]
    ]
    assert len(shown) == 1
    printed = _status()
    url = re.escape(LMSTUDIO_ADDRESS.url)
    assert re.fullmatch(rf"LM Studio: not reachable at {url} \(.+\)", shown[0][0])
    assert shown[0][1:] == printed[1:]
    steps = [line for line in shown[0] if re.match(r"  \d\. ", line)]
    assert steps == [f"  1. {LMSTUDIO_INSTALL}", f"  2. {AGAIN}"]
    assert shown[0][-len(LMSTUDIO_SETTINGS) :] == LMSTUDIO_SETTINGS


@pytest.mark.parametrize(("name", "language"), READMES)
def test_lm_studio_is_asked_two_things_and_sent_the_same_facts(name: str, language: str) -> None:
    # [0019.21]
    text = _said(name, AI)
    assert "`GET /v1/models`" in text
    assert "`POST /v1/chat/completions`" in text
    if language == "en":
        assert "never one that downloads, loads or unloads a model" in text
        assert "the same facts, to either server" in text
    else:
        assert "никогда не просит скачать, загрузить или выгрузить модель" in text
        assert "те же факты, какому бы серверу" in text


@pytest.mark.parametrize(("name", "language"), READMES)
def test_the_window_s_server_in_its_own_words(name: str, language: str) -> None:
    # [0019.21] the choice, the variable that wins, the settings file, the recommendation
    text = _said(name, DESKTOP)
    settings = text.split(f"**{CATALOG['page.settings'][language]}**", 1)[1]
    assert f"{CATALOG['settings.server'][language]}: Ollama" in settings
    assert "LM Studio" in settings
    assert f"`{SERVER_VARIABLE}`" in settings
    assert all(f"`{model}`" in settings for model in RECOMMENDED + LMSTUDIO_RECOMMENDED)
    assert "Discover" in settings
    assert "`server`" in text


@pytest.mark.parametrize(("name", "language"), READMES)
def test_the_release_s_files(name: str, language: str) -> None:
    # [0019.21] the wheel from the release when PyPI has none
    install = _said(name, "Install")
    for file in (WHEEL, SDIST, "SHA256SUMS.txt"):
        assert f"`{file}`" in install, file
    development = _said(name, "Development")
    assert "`PUBLISH_TO_PYPI`" in development
    assert "`Kresorter X.Y.Z`" in development


def test_pipx_installs_the_wheel_of_the_release_too() -> None:
    # [0019.21] with the window or without it, as from PyPI
    commands = [
        line.split("#")[0].split()
        for block in blocks(_lines("README.md", "Linux"), "bash")
        for line in block
    ]
    assert ["pipx", "install", f'"./{WHEEL}[ui]"'] in commands
    assert ["pipx", "install", f"./{WHEEL}"] in commands
    assert WHEEL.replace("<version>", __version__) == f"kresorter-{__version__}-py3-none-any.whl"


@pytest.mark.parametrize(("name", "language"), READMES)
def test_the_licence(name: str, language: str) -> None:
    # [0019.21] [0019.20] in both languages
    text = _said(name, "License")
    for said in ("MIT", "[`LICENSE`](LICENSE)", "PSF", "LGPL-3.0", "`THIRD-PARTY-NOTICES.txt`"):
        assert said in text, said


# --- the changelog -----------------------------------------------------------------------------


def test_the_changelog_says_the_same_for_its_users() -> None:
    # [0019.22]
    text = _changelog()
    assert "in the window's language" in text
    assert "LM Studio" in text
    assert f"`{SERVER_VARIABLE}`" in text
    assert "icon" in text
    settings = _entry(text, CATALOG["page.settings"]["en"])
    assert CATALOG["settings.server"]["en"] in settings
    assert "LM Studio" in settings
    assert "MIT" in settings
    files = [
        f"Kresorter-{__version__}-setup.exe",
        f"Kresorter-{__version__}-portable.zip",
        WHEEL.replace("<version>", __version__),
        SDIST.replace("<version>", __version__),
        "SHA256SUMS.txt",
    ]
    assert [file for file in files if f"`{file}`" not in text] == []
    assert "GitHub release" in text
    assert "LGPL-3.0" in text
    assert "`README.ru.md`" in text


# --- the roadmap --------------------------------------------------------------------------------


def test_the_roadmap_records_the_work_and_the_accepted_limitations() -> None:
    # [0019.23]
    roadmap = "docs/roadmap.md"
    titles = [title for _, title, _ in headings(_read(roadmap))]
    assert titles.index(DONE) < titles.index(LIMITS) < titles.index("Left for later")
    done = " ".join(" ".join(section(_read(roadmap), DONE)).split())
    assert f"]({DECISION.removeprefix('docs/')})" in done
    for words in ("LM Studio", "`README.ru.md`", "icon", "`PUBLISH_TO_PYPI`", "LicenseFile"):
        assert words in done, words
    limits = " ".join(" ".join(section(_read(roadmap), LIMITS)).split())
    assert len(_limitations()) == 4
    assert [title for title in _limitations() if title not in limits] == []


@pytest.mark.parametrize("package", ["llm", "ui"])
def test_the_layout_names_every_module(package: str) -> None:
    # [0019.23] lmstudio and brand came with this decision.
    layout = _read("docs/roadmap.md").split("## Target package layout", 1)[1].splitlines()
    [start] = [index for index, line in enumerate(layout) if f"── {package}/" in line]
    end = next((i for i in range(start + 1, len(layout)) if "──" in layout[i]), len(layout))
    line = " ".join(layout[start:end])
    found = sorted(path.stem for path in (ROOT / "src" / "kresorter" / package).glob("*.py"))
    assert [name for name in found if not name.startswith("__") and name not in line] == []
