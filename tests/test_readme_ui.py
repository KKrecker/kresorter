"""The README's section on the desktop app (decision 0014, item 41).

The section names the extra and its install command, the system libraries Qt needs on Linux
(those CI installs), how to start the window, its pages in the sidebar's order, that it acts
only after a confirmation, its two languages and the one file it keeps. No Qt is needed here.
"""

import json
import tomllib
from pathlib import Path

from safeclean.ui.settings import DEFAULTS, SETTINGS_NAME
from safeclean.ui.texts import CATALOG
from support.markdown import blocks, section

ROOT = Path(__file__).resolve().parents[1]
TITLE = "Desktop app (optional)"
PAGES = ("overview", "findings", "quarantine", "organize", "autostart", "settings")
ACTIONS = ("quarantine", "restore", "delete", "organize", "undo", "disable", "enable", "recover")


def desktop() -> list[str]:
    return section((ROOT / "README.md").read_text(encoding="utf-8"), TITLE)


def commands() -> list[str]:
    return [line for block in blocks(desktop(), "bash") for line in block]


def pyproject() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_section_installs_the_extra_and_starts_the_window_both_ways() -> None:
    # [0014.41] The extra and the GUI script are those of pyproject.toml.
    data = pyproject()
    project = data["project"]
    assert isinstance(project, dict)
    assert "ui" in project["optional-dependencies"]
    assert project["gui-scripts"] == {"safeclean-ui": "safeclean.ui.launch:main"}
    words = [line.split("#")[0].split() for line in commands()]
    assert ["pip", "install", '"safeclean[ui]"'] in words
    assert ["safeclean-ui"] in words
    assert ["python", "-m", "safeclean.ui"] in words


def test_the_section_names_the_system_libraries_ci_installs() -> None:
    # [0014.41] The same packages as the workflow, in one command.
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    [ci] = [
        line.split("apt-get install -y")[1].split()
        for line in workflow.splitlines()
        if "apt-get install" in line
    ]
    [shown] = [
        line.split("apt-get install")[1].split() for line in commands() if "apt-get install" in line
    ]
    assert shown == ci
    assert "Linux" in "\n".join(desktop())


def test_the_section_names_the_pages_in_the_sidebar_s_order() -> None:
    # [0014.41] Each page once, bold, in order, by the window's English name.
    text = "\n".join(desktop())
    names = [f"**{CATALOG[f'page.{page}']['en']}**" for page in PAGES]
    places = [text.find(name) for name in names]
    assert all(place >= 0 for place in places)
    assert places == sorted(places)


def test_the_section_says_every_action_waits_for_a_confirmation() -> None:
    # [0014.41]
    text = " ".join(desktop())
    assert "until you confirm" in text
    assert all(action in text.casefold() for action in ACTIONS)
    assert "Cancel" in text


def test_the_section_names_both_languages_and_the_one_file_kept() -> None:
    # [0014.41] The file's defaults as the window takes them.
    text = " ".join(desktop())
    assert "English" in text
    assert "Russian" in text
    assert f"`{SETTINGS_NAME}`" in text
    defaults = {"language": DEFAULTS.language, "include_machine": DEFAULTS.include_machine}
    assert f"`{json.dumps(defaults)}`" in text
