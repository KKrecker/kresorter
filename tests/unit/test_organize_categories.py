"""Organize's categories: a fixed table, as data (decision 0012, items 21-23), with the kinds
and extensions decision 0020 adds (item 12).

The table lives in ``organize/categories.toml``, in the order plans list it; one extension has
one category. Every extension has an example here, as every junk rule has one, and the table is
the one the decisions show.
"""

import re
from pathlib import Path

import pytest

from kresorter.organize.categories import (
    Category,
    CategoryTable,
    default_categories,
    default_table,
    load_categories,
)

DECISIONS = Path(__file__).resolve().parents[2] / "docs" / "decisions"
TABLES = (DECISIONS / "0012-organize.md", DECISIONS / "0020-owners-requests-3.md")
ROW = re.compile(r"^ *\| `([A-Z0-9][A-Za-z0-9 ]*)` \| (.+) \|$", re.MULTILINE)

EXAMPLES: list[tuple[str, str]] = [
    ("holiday.jpg", "Images"),
    ("scan.jpeg", "Images"),
    ("screenshot.png", "Images"),
    ("animation.gif", "Images"),
    ("banner.webp", "Images"),
    ("IMG_0001.heic", "Images"),
    ("IMG_0002.heif", "Images"),
    ("old.bmp", "Images"),
    ("fax.tif", "Images"),
    ("print.tiff", "Images"),
    ("logo.svg", "Images"),
    ("IMG_0003.cr2", "Images"),
    ("DSC_0004.nef", "Images"),
    ("DSC0005.arw", "Images"),
    ("raw.dng", "Images"),
    ("film.mp4", "Videos"),
    ("series.mkv", "Videos"),
    ("old.avi", "Videos"),
    ("clip.mov", "Videos"),
    ("talk.webm", "Videos"),
    ("episode.m4v", "Videos"),
    ("trailer.wmv", "Videos"),
    ("tape.mpg", "Videos"),
    ("tape.mpeg", "Videos"),
    ("song.mp3", "Audio"),
    ("album.flac", "Audio"),
    ("sample.wav", "Audio"),
    ("track.ogg", "Audio"),
    ("track.oga", "Audio"),
    ("voice.opus", "Audio"),
    ("podcast.m4a", "Audio"),
    ("stream.aac", "Audio"),
    ("legacy.wma", "Audio"),
    ("invoice.pdf", "Documents"),
    ("letter.doc", "Documents"),
    ("letter.docx", "Documents"),
    ("essay.odt", "Documents"),
    ("memo.rtf", "Documents"),
    ("notes.txt", "Documents"),
    ("README.md", "Documents"),
    ("budget.xls", "Documents"),
    ("budget.xlsx", "Documents"),
    ("sheet.ods", "Documents"),
    ("export.csv", "Documents"),
    ("slides.ppt", "Documents"),
    ("slides.pptx", "Documents"),
    ("talk.odp", "Documents"),
    ("novel.epub", "Documents"),
    ("photos.zip", "Archives"),
    ("photos.rar", "Archives"),
    ("photos.7z", "Archives"),
    ("backup.tar", "Archives"),
    ("log.gz", "Archives"),
    ("source.tgz", "Archives"),
    ("dump.bz2", "Archives"),
    ("kernel.xz", "Archives"),
    ("data.zst", "Archives"),
    ("backup.tar.gz", "Archives"),
    ("backup.tar.bz2", "Archives"),
    ("backup.tar.xz", "Archives"),
    ("backup.tar.zst", "Archives"),
    ("distro.iso", "Archives"),
    ("setup.exe", "Installers"),
    ("tool.msi", "Installers"),
    ("app.dmg", "Installers"),
    ("app.pkg", "Installers"),
    ("tool.deb", "Installers"),
    ("tool.rpm", "Installers"),
    ("Tool.AppImage", "Installers"),
    ("app.flatpakref", "Installers"),
    ("photo.avif", "Images"),
    ("photo.jxl", "Images"),
    ("favicon.ico", "Images"),
    ("IMG_0006.cr3", "Images"),
    ("DSCF0007.raf", "Images"),
    ("P0008.orf", "Images"),
    ("P0009.rw2", "Images"),
    ("poster.psd", "Images"),
    ("drawing.xcf", "Images"),
    ("painting.kra", "Images"),
    ("phone.3gp", "Videos"),
    ("old.flv", "Videos"),
    ("disc.m2ts", "Videos"),
    ("camera.mts", "Videos"),
    ("VTS_01_1.vob", "Videos"),
    ("clip.ogv", "Videos"),
    ("film.srt", "Videos"),
    ("anime.ass", "Videos"),
    ("anime.ssa", "Videos"),
    ("talk.vtt", "Videos"),
    ("master.aiff", "Audio"),
    ("master.aif", "Audio"),
    ("tune.mid", "Audio"),
    ("tune.midi", "Audio"),
    ("album.ape", "Audio"),
    ("voice.amr", "Audio"),
    ("concert.mka", "Audio"),
    ("song.lrc", "Audio"),
    ("scan.djvu", "Documents"),
    ("book.fb2", "Documents"),
    ("book.mobi", "Documents"),
    ("book.azw3", "Documents"),
    ("print.xps", "Documents"),
    ("print.oxps", "Documents"),
    ("letter.pages", "Documents"),
    ("budget.numbers", "Documents"),
    ("drivers.cab", "Archives"),
    ("data.lz", "Archives"),
    ("data.lzma", "Archives"),
    ("photos.zipx", "Archives"),
    ("source.tar.lz", "Archives"),
    ("app.msix", "Installers"),
    ("app.msixbundle", "Installers"),
    ("app.appx", "Installers"),
    ("app.appxbundle", "Installers"),
    ("game.apk", "Installers"),
    ("game.xapk", "Installers"),
    ("distro.torrent", "Torrents"),
    ("Inter.ttf", "Fonts"),
    ("Inter.otf", "Fonts"),
    ("inter.woff", "Fonts"),
    ("inter.woff2", "Fonts"),
    ("bracket.stl", "3D models"),
    ("bracket.3mf", "3D models"),
    ("part.step", "3D models"),
    ("part.stp", "3D models"),
    ("character.fbx", "3D models"),
    ("scene.glb", "3D models"),
    ("scene.gltf", "3D models"),
    ("scene.blend", "3D models"),
]

TABLE = """
[[category]]
name = "Images"
extensions = ["jpg", "jpeg"]

[[category]]
name = "Archives"
extensions = ["gz", "tar.gz"]
"""


# --- the table ---------------------------------------------------------------------------------


def test_the_categories_are_english_and_in_table_order() -> None:
    # [0012.21] [0012.23] [0020.12] fixed in step 5: their names are directory names; the
    # three of 0020 after the others
    assert [category.name for category in default_categories()] == [
        "Images",
        "Videos",
        "Audio",
        "Documents",
        "Archives",
        "Installers",
        "Torrents",
        "Fonts",
        "3D models",
    ]
    assert default_table().names == tuple(category.name for category in default_categories())


def test_the_table_is_the_one_the_decisions_show() -> None:
    # [0012.21] [0020.12] 0012's table, and the extensions and kinds 0020 adds
    shown: dict[str, set[str]] = {}
    for decision in TABLES:
        for name, cells in ROW.findall(decision.read_text(encoding="utf-8")):
            found = re.findall(r"[a-z0-9.]+", " ".join(re.findall(r"`([^`]+)`", cells)))
            shown.setdefault(name, set()).update(found)
    assert shown == {c.name: set(c.extensions) for c in default_categories()}


@pytest.mark.parametrize(("name", "category"), EXAMPLES)
def test_examples(name: str, category: str) -> None:
    # [0012.21] [0020.12]
    found = default_table().match(name)
    assert found is not None
    assert found.category == category


def test_every_extension_has_an_example() -> None:
    # [0012.21]
    table = default_table()
    matched = {found.extension for name, _ in EXAMPLES if (found := table.match(name))}
    assert matched == {ext for category in default_categories() for ext in category.extensions}


# --- matching ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "category", "extension"),
    [
        ("photo.JPG", "Images", "jpg"),
        ("PHOTO.Jpeg", "Images", "jpeg"),
        ("backup.tar.gz", "Archives", "tar.gz"),
        ("BACKUP.TAR.GZ", "Archives", "tar.gz"),
        ("notes.gz", "Archives", "gz"),
        ("my.holiday.photo.jpg", "Images", "jpg"),
        ("photo.jpg.exe", "Installers", "exe"),
    ],
)
def test_extensions_match_regardless_of_case_the_longest_first(
    name: str, category: str, extension: str
) -> None:
    # [0012.22]
    found = default_table().match(name)
    assert found is not None
    assert (found.category, found.extension) == (category, extension)


@pytest.mark.parametrize(
    "name",
    [
        "README",
        "page.html",
        "page.htm",
        "library.dll",
        "photo.jpg.part",
        "archive.tar.",
        "script.py",
        "data.json",
        "settings.ini",
        "run.bat",
        "disk.vhdx",
        "disk.vmdk",
    ],
)
def test_a_name_whose_extension_is_not_in_the_table_has_no_category(name: str) -> None:
    # [0012.13] [0012.16] [0020.12] there is no Other; web pages are not in the table, nor code,
    # data, settings or a virtual machine's disk
    assert default_table().match(name) is None


def test_a_table_is_read_from_its_text() -> None:
    # [0012.21]
    categories = load_categories(TABLE)
    assert categories == (
        Category("Images", ("jpg", "jpeg")),
        Category("Archives", ("gz", "tar.gz")),
    )
    found = CategoryTable(categories).match("x.tar.gz")
    assert found is not None
    assert (found.category, found.extension) == ("Archives", "tar.gz")


# --- validation --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "expected \\[\\[category\\]\\] tables"),
        ('[[category]]\nextensions = ["jpg"]', "missing 'name'"),
        ('[[category]]\nname = "Images"', "missing 'extensions'"),
        ('[[category]]\nname = "Images"\nextensions = []', "no extensions"),
        ('[[category]]\nname = "Images"\nextensions = "jpg"', "must be a list of strings"),
        ('[[category]]\nname = "Images"\nextensions = ["jpg"]\nicon = "x"', "unknown key 'icon'"),
        ('[[category]]\nname = ""\nextensions = ["jpg"]', "not a directory name"),
        ('[[category]]\nname = "A/B"\nextensions = ["jpg"]', "not a directory name"),
        ('[[category]]\nname = ".."\nextensions = ["jpg"]', "not a directory name"),
        ('[[category]]\nname = "Images"\nextensions = ["JPG"]', "lower case"),
        ('[[category]]\nname = "Images"\nextensions = [".jpg"]', "without its dot"),
        ('[[category]]\nname = "Images"\nextensions = ["jpg."]', "without its dot"),
        ('[[category]]\nname = "Images"\nextensions = [""]', "without its dot"),
        ('[[category]]\nname = "Images"\nextensions = ["j/g"]', "not part of a file name"),
        (
            '[[category]]\nname = "Images"\nextensions = ["jpg"]\n'
            '[[category]]\nname = "Images"\nextensions = ["png"]',
            "category 'Images' twice",
        ),
        (
            '[[category]]\nname = "Images"\nextensions = ["jpg"]\n'
            '[[category]]\nname = "Photos"\nextensions = ["jpg"]',
            "'jpg' in two categories",
        ),
    ],
)
def test_an_invalid_table_is_rejected(text: str, message: str) -> None:
    # [0012.21] one extension, one category
    with pytest.raises(ValueError, match=message):
        load_categories(text)
