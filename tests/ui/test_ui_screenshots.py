"""The screenshots' script (decision 0015, items 26 and 27), run here for one screen into a
temporary folder, so that it cannot fall behind the window.

The window's tests reach no live system (``support.live``): had the script read anything of
the user's, the scan or autostart of the running system, this would fail. Home and the data
and settings folders are the made-up home's while it runs, and the test's again after.
"""

import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from support import screenshots
from support.png import png_size

ROOT = Path(__file__).resolve().parents[2]


def test_the_prototype_s_six_screens_are_in_docs_screenshots() -> None:
    # [0015.26] in English, at 1280 x 800
    assert screenshots.SCREENS == (
        "overview",
        "findings",
        "confirmation",
        "organize",
        "autostart",
        "findings-dark",
    )
    assert screenshots.OUT == ROOT / "docs" / "screenshots"
    assert sorted(path.name for path in screenshots.OUT.iterdir()) == sorted(
        f"{screen}.png" for screen in screenshots.SCREENS
    )
    assert (screenshots.WIDTH, screenshots.HEIGHT) == (1280, 800)


def test_the_script_makes_the_confirmation_over_findings_as_the_readme_shows_it(
    qapp: QApplication, tmp_path: Path
) -> None:
    # [0015.27] the real dialog over the window; then cancelled, and home is the test's again
    homes = {name: os.environ.get(name) for name in screenshots.HOME_VARIABLES}
    out = tmp_path / "out"

    made = screenshots.shoot(out, ["confirmation"])

    assert made == [out / "confirmation.png"]
    assert png_size(made[0]) == (1280, 800)
    assert {name: os.environ.get(name) for name in screenshots.HOME_VARIABLES} == homes
    assert sorted(path.name for path in out.iterdir()) == ["confirmation.png"]


def test_the_command_names_what_it_wrote(
    qapp: QApplication, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # [0015.26]
    assert screenshots.main(["autostart"], tmp_path) == 0

    assert capsys.readouterr().out == f"{tmp_path / 'autostart.png'}\n"
    assert png_size(tmp_path / "autostart.png") == (1280, 800)


def test_a_screen_the_prototype_has_not_is_refused(qapp: QApplication, tmp_path: Path) -> None:
    # [0015.26]
    with pytest.raises(ValueError, match=r"no screen 'settings': the screens are overview, "):
        screenshots.shoot(tmp_path / "out", ["settings"])
    assert not (tmp_path / "out").exists()
