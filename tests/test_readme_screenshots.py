"""The README shows the window (decision 0015, item 27): each image it shows is in
``docs/screenshots``, a PNG of 1280 x 800 with a text that says what it shows, and every image
there is shown, once; the Overview comes first, before the first section. No Qt is needed here:
``tests/ui/test_ui_screenshots.py`` runs the script that makes them.
"""

import re
from pathlib import Path

import pytest

from support.png import png_size

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "docs" / "screenshots"
IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")


def readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def images() -> list[tuple[str, str]]:
    """(text, target) of every image the README shows, in order."""
    return IMAGE.findall(readme())


def test_each_image_the_readme_shows_is_a_screenshot_of_1280_by_800() -> None:
    # [0015.27]
    shown = images()
    assert shown
    for text, target in shown:
        assert target.startswith("docs/screenshots/")
        assert text.strip()
        assert png_size(ROOT / target) == (1280, 800)


def test_every_screenshot_is_shown_once() -> None:
    # [0015.27]
    targets = [target for _, target in images()]
    assert len(targets) == len(set(targets))
    assert sorted(targets) == sorted(f"docs/screenshots/{path.name}" for path in FOLDER.iterdir())


def test_the_overview_comes_first_before_the_first_section() -> None:
    # [0015.27] the window, under the title, as it opens after a scan
    text = readme()
    first = IMAGE.search(text)
    assert first is not None
    assert first[2] == "docs/screenshots/overview.png"
    assert first.start() < text.index("\n## ")


def test_a_file_that_is_not_a_png_has_no_size(tmp_path: Path) -> None:
    # [0015.27]
    path = tmp_path / "overview.png"
    path.write_bytes(b"GIF89a" + bytes(30))
    with pytest.raises(ValueError, match=r"overview\.png: not a PNG"):
        png_size(path)
