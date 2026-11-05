"""The README in Russian (decision 0019, items 15 and 16).

``README.ru.md`` says what ``README.md`` says: the same headings at the same levels in the same
order, the same code blocks, the same images and the same link targets, its text translated; a
link to a heading of the page leads to the heading at the same place in each. Each begins, under
its title, with the switch to the other. The sdist carries both. The comparison is tried first
on made-up text, where each kind of difference must be found.
"""

import tomllib
from pathlib import Path

import pytest

from support.markdown import headings
from support.readmes import SWITCHES, differences, fences, images, levels, links, slug

ROOT = Path(__file__).resolve().parents[1]
NAMES = {"Kresorter", "Windows", "Linux"}  # headings that are names, the same in both

ENGLISH = """# Title

**English** | [Русский](README.ru.md)

Status: see [the roadmap](docs/roadmap.md) and [Install](#install-it).

![The window](docs/window.png)

## Install it

```bash
pip install kresorter   # the commands
```

### On Linux: `pipx`

See [Install](#install-it) and [pipx](https://pipx.pypa.io).
"""

RUSSIAN = """# Title

[English](README.md) | **Русский**

Состояние: смотрите [план](docs/roadmap.md) и [установку](#установка-программы).

![Окно программы](docs/window.png)

## Установка программы

```bash
pip install kresorter   # the commands
```

### Под Linux: `pipx`

Смотрите [установку](#установка-программы) и [pipx](https://pipx.pypa.io).
"""


def _readme(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


# --- how the two are compared, on made-up text -------------------------------------------------


@pytest.mark.parametrize(
    ("title", "anchor"),
    [
        ("Desktop app (optional)", "desktop-app-optional"),
        ("Reports: `scan`, `analyze`", "reports-scan-analyze"),
        ("What each system can do", "what-each-system-can-do"),
        ("Установка программы", "установка-программы"),
        ("Объяснения ИИ (по желанию)", "объяснения-ии-по-желанию"),
    ],
)
def test_a_heading_has_the_anchor_github_gives_it(title: str, anchor: str) -> None:
    # [0019.15]
    assert slug(title) == anchor


def test_the_parts_compared_are_read_outside_the_switch_and_the_code_blocks() -> None:
    # [0019.15] a link to a heading is that heading's place: 0 the title, 1 "Install it"
    assert levels(ENGLISH) == [1, 2, 3]
    assert fences(ENGLISH) == [["```bash", "pip install kresorter   # the commands", "```"]]
    assert images(ENGLISH) == ["docs/window.png"]
    assert links(ENGLISH) == ["docs/roadmap.md", "#1", "#1", "https://pipx.pypa.io"]
    assert links(RUSSIAN) == links(ENGLISH)


def test_two_readmes_that_say_the_same_differ_in_nothing() -> None:
    # [0019.15]
    assert differences(ENGLISH, RUSSIAN) == []


@pytest.mark.parametrize(
    ("old", "new", "found"),
    [
        (
            SWITCHES["README.ru.md"],
            SWITCHES["README.md"],
            ["README.ru.md does not begin, under its title, with " + SWITCHES["README.ru.md"]],
        ),
        (
            "### Под Linux",
            "## Под Linux",
            ["the headings' levels differ at 2: 3 in README.md, 2 in README.ru.md"],
        ),
        (
            "### Под Linux: `pipx`\n",
            "",
            ["the headings' levels differ at 2: 3 in README.md, None in README.ru.md"],
        ),
        ("# the commands", "# все команды", ["the code blocks differ at 0: "]),
        ("```bash", "```sh", ["the code blocks differ at 0: "]),
        (
            "(docs/window.png)",
            "(docs/screen.png)",
            ["the images differ at 0: 'docs/window.png' in README.md, 'docs/screen.png' in"],
        ),
        (
            "(docs/roadmap.md)",
            "(docs/roadmap.ru.md)",
            ["the link targets differ at 0: 'docs/roadmap.md' in README.md, 'docs/roadmap.ru.md'"],
        ),
        (
            "(#установка-программы)",
            "(#title)",
            ["the link targets differ at 1: '#1' in README.md, '#0' in README.ru.md"],
        ),
        (
            "(#установка-программы)",
            "(#install-it)",
            [
                "README.ru.md: no heading has the anchor install-it",
                "the link targets differ at 1: '#1' in README.md, '#?install-it' in README.ru.md",
            ],
        ),
        (
            " и [pipx](https://pipx.pypa.io)",
            "",
            ["the link targets differ at 3: 'https://pipx.pypa.io' in README.md, None in"],
        ),
    ],
)
def test_each_difference_item_15_names_is_found(old: str, new: str, found: list[str]) -> None:
    # [0019.15] [0019.16]
    assert RUSSIAN.count(old) >= 1
    told = differences(ENGLISH, RUSSIAN.replace(old, new, 1))
    assert len(told) == len(found)
    for said, start in zip(told, found, strict=True):
        assert said.startswith(start)


def test_the_english_readme_is_checked_too() -> None:
    # [0019.15]
    told = differences(ENGLISH.replace(SWITCHES["README.md"], "[Русский](README.ru.md)"), RUSSIAN)
    assert told == [
        "README.md does not begin, under its title, with " + SWITCHES["README.md"],
        "the link targets differ at 0: 'README.ru.md' in README.md, 'docs/roadmap.md' in"
        " README.ru.md",
    ]


def test_a_readme_with_nothing_in_it_has_no_switch() -> None:
    # [0019.15]
    assert differences("", RUSSIAN)[0] == (
        "README.md does not begin, under its title, with " + SWITCHES["README.md"]
    )


# --- the two READMEs ----------------------------------------------------------------------------


def test_the_russian_readme_says_what_the_english_one_says() -> None:
    # [0019.15] [0019.16] the switch, the headings' levels, the code blocks, the images and the
    # link targets; every link to a heading leads to one
    assert differences(_readme("README.md"), _readme("README.ru.md")) == []


def test_each_heading_but_a_name_is_translated() -> None:
    # [0019.15]
    english = [title for _, title, _ in headings(_readme("README.md"))]
    russian = [title for _, title, _ in headings(_readme("README.ru.md"))]
    assert len(english) == len(russian)
    for ours, theirs in zip(english, russian, strict=True):
        assert (ours == theirs) == (ours in NAMES), (ours, theirs)


def test_the_sdist_carries_the_russian_readme() -> None:
    # [0019.16] the wheel and the sdist are built and checked in tests/test_artifacts.py
    with (ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)
    included = project["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]
    assert "README.ru.md" in included
