"""The README's section on AI explanations (decision 0013, item 16).

The section says that Ollama and the model are installed by the user, never by kresorter,
shows the steps and both settings as ``kresorter llm status`` prints them, run here against a
port nothing listens on, and lists what is sent for each kind of subject (item 17) and that
nothing else is. The section is read as Markdown: up to the next heading of its level or above,
a ``#`` inside a code block being no heading.
"""

import io
import re
import socket
from pathlib import Path

import pytest

from kresorter import cli
from kresorter.cli_llm import AGAIN, INSTALL, PULL, SETTINGS
from kresorter.environment import Environment
from kresorter.llm.settings import DEFAULT_ADDRESS, DEFAULT_MODEL, MODEL_VARIABLE, URL_VARIABLE
from support.markdown import blocks, headings, section

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
TITLE = "AI explanations (optional)"
CODE = re.compile(r"`([^`]+)`")
FACTS = {  # item 17, in order
    "finding": ["level", "reasons", "extension"],
    "autostart": ["source", "scope", "name", "program", "enabled"],
    "stay": ["reason", "extension"],
}
NOT_SENT = [
    "the path",
    "the folder",
    "the size",
    "the times",
    "the digest",
    "the location",
    "the whole command",
    "notes",
    "details",
]
EXPLAINED = ["analyze", "autostart list", "organize move"]


def prose(lines: list[str]) -> str:
    """The lines outside code blocks, every run of whitespace one space."""
    shown: list[str] = []
    fenced = False
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced:
            shown.append(line)
    return " ".join(" ".join(shown).split())


def bullets(lines: list[str]) -> list[str]:
    """Each list item that starts a line, with the indented lines that follow it."""
    found: list[str] = []
    joining = False
    for line in lines:
        if line.startswith("- "):
            found.append(line[2:])
            joining = True
        elif joining and line.startswith("  "):
            found[-1] += " " + line
        else:
            joining = False
    return [" ".join(item.split()) for item in found]


def readme() -> list[str]:
    return section(README.read_text(encoding="utf-8"), TITLE)


def status_when_nothing_answers() -> list[str]:
    """What ``kresorter llm status`` prints when nothing listens at the address."""
    with socket.create_server(("127.0.0.1", 0)) as taken:
        url = f"http://127.0.0.1:{taken.getsockname()[1]}"
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        ["llm", "status"], out=out, err=err, environment=Environment(llm_env={URL_VARIABLE: url})
    )
    assert (code, err.getvalue()) == (1, "")
    return out.getvalue().splitlines()


# --- how the README is read, on made-up text -------------------------------------------------


MADE_UP = """# Title
## Usage
```bash
# a comment, not a heading
kresorter scan
```
### AI explanations (optional)
- `one`: `a`,
  `b`
  - nested, `c`

- `two`, ```d```
### Exit codes
```text
## Not a heading
```
## Development
"""


def test_a_section_ends_at_a_heading_of_its_level_or_above() -> None:
    # [0013.16]
    assert headings(MADE_UP) == [
        (1, "Title", 0),
        (2, "Usage", 1),
        (3, TITLE, 6),
        (3, "Exit codes", 12),
        (2, "Development", 16),
    ]
    usage = section(MADE_UP, "Usage")
    assert (usage[0], usage[-1], len(usage)) == ("```bash", "```", 14)
    assert blocks(usage, "bash") == [["# a comment, not a heading", "kresorter scan"]]
    assert blocks(usage, "text") == [["## Not a heading"]]
    assert prose(usage) == (
        "### AI explanations (optional) - `one`: `a`, `b` - nested, `c` - `two`, ```d``` "
        "### Exit codes"
    )
    assert bullets(section(MADE_UP, TITLE)) == ["`one`: `a`, `b` - nested, `c`", "`two`, ```d```"]
    assert section(MADE_UP, "Development") == []


@pytest.mark.parametrize(
    "text", ["# Other\n", f"## {TITLE}\n## {TITLE}\n", f"```\n## {TITLE}\n```\n"]
)
def test_a_title_must_be_a_heading_exactly_once(text: str) -> None:
    # [0013.16]
    with pytest.raises(AssertionError, match="is a heading"):
        section(text, TITLE)


# --- the README ------------------------------------------------------------------------------


def test_ollama_and_the_model_are_installed_by_the_user_never_by_kresorter() -> None:
    # [0013.16]
    text = prose(readme())
    assert "Ollama and the model are installed by you, never by kresorter" in text
    assert "kresorter launches no program" in text


def test_the_steps_and_the_settings_are_those_llm_status_prints() -> None:
    # [0013.16] Every step of item 15: Ollama is not reached, so none is left out.
    shown = [block for block in blocks(readme(), "text") if block[0].startswith("Ollama: ")]
    assert len(shown) == 1
    printed = status_when_nothing_answers()
    url = re.escape(DEFAULT_ADDRESS.url)
    assert re.fullmatch(rf"Ollama: not reachable at {url} \(.+\)", shown[0][0])
    assert shown[0][1:] == printed[1:]
    steps = [line for line in shown[0] if re.match(r"  \d\. ", line)]
    assert steps == [f"  1. {INSTALL}", f"  2. {PULL.format(DEFAULT_MODEL)}", f"  3. {AGAIN}"]
    assert shown[0][-2:] == SETTINGS


def test_both_settings_are_explained() -> None:
    # [0013.16]
    text = prose(readme())
    for variable in (URL_VARIABLE, MODEL_VARIABLE):
        assert f"`{variable}`" in text
    assert f"`{DEFAULT_ADDRESS.url}`" in text
    assert f"`{DEFAULT_MODEL}`" in text


def test_what_is_sent_for_each_kind() -> None:
    # [0013.16] The facts of item 17, in its order, each as the label names it.
    names = {name for facts in FACTS.values() for name in facts}
    listed: dict[str, list[str]] = {}
    for item in bullets(readme()):
        kind, *rest = CODE.findall(item) or [""]
        if kind in FACTS:
            listed[kind] = [name for name in rest if name in names]
            assert item.startswith(f"`{kind}`")
    assert listed == FACTS
    assert "`junk_cache:python-bytecode`" in prose(readme())


def test_nothing_else_is_sent() -> None:
    # [0013.16]
    text = prose(readme())
    start = text.index("Nothing else is sent")
    sentence = text[start : text.index(".", start)]
    assert [part for part in NOT_SENT if part not in sentence] == []
    assert "a file's content" in sentence


def test_the_commands_that_explain() -> None:
    # [0013.16] Never with --yes; a comment is not part of a command.
    commands = [line.split("#")[0].strip() for block in blocks(readme(), "bash") for line in block]
    for command in EXPLAINED:
        given = [line for line in commands if line.startswith(f"kresorter {command} ")]
        assert any(line.endswith(" --explain") for line in given), command
    assert [line for line in commands if "--explain" in line and "--yes" in line] == []
    assert "kresorter llm status" in commands
