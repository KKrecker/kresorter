"""Junk heuristics: rules are data (TOML), the engine only interprets them.

Rule semantics:
* ``dirs``: path patterns ("a/b/*/c", segments are globs) that must appear as *consecutive*
  parent directories; a leading "/" anchors the pattern at the filesystem root.
* ``files``: file-name globs.
* A rule with both matches only when both match. The first matching rule (file order) wins.
* Matching is case-insensitive on Windows and macOS, case-sensitive on Linux.
"""

from pathlib import PurePath, PurePosixPath, PureWindowsPath

import pytest

from kresorter.core.heuristics import (
    JunkCategory,
    JunkClassifier,
    JunkMatch,
    Platform,
    default_rules,
    load_rules,
)

RULES = """
[[rule]]
id = "pycache"
category = "cache"
description = "Python bytecode"
dirs = ["__pycache__"]

[[rule]]
id = "browser"
category = "cache"
description = "Browser cache"
dirs = ["User Data/*/Cache"]

[[rule]]
id = "tmp-root"
category = "temp"
description = "System temp"
dirs = ["/tmp"]
platforms = ["linux", "darwin"]

[[rule]]
id = "thumbcache"
category = "thumbnails"
description = "Explorer thumbnail cache"
dirs = ["Microsoft/Windows/Explorer"]
files = ["thumbcache_*.db"]
platforms = ["windows"]

[[rule]]
id = "tmp-ext"
category = "temp"
description = "Temporary file"
files = ["*.tmp"]
"""


def classifier(platform: Platform) -> JunkClassifier:
    return JunkClassifier(load_rules(RULES), platform=platform)


def rule_id(platform: Platform, path: PurePath) -> str | None:
    match = classifier(platform).classify(path)
    return match.rule_id if match else None


# --- matching semantics ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("/home/a/proj/__pycache__/m.pyc", "pycache", id="dir-anywhere"),
        pytest.param("/home/a/__pycache__/sub/m.pyc", "pycache", id="nested-below-dir"),
        pytest.param("/home/a/__pycache__", None, id="dir-name-as-file"),
        pytest.param("/home/a/User Data/Default/Cache/f_01", "browser", id="glob-segment"),
        pytest.param("/home/a/User Data/Default/x/Cache/f", None, id="not-consecutive"),
        pytest.param("/tmp/a.bin", "tmp-root", id="anchored"),
        pytest.param("/home/a/tmp/a.bin", None, id="anchored-not-elsewhere"),
        pytest.param("/home/a/report.tmp", "tmp-ext", id="file-glob"),
        pytest.param("/tmp/x.tmp", "tmp-root", id="first-rule-wins"),
        pytest.param("/home/a/__PYCACHE__/m.pyc", None, id="linux-case-sensitive"),
        pytest.param("/home/a/notes.txt", None, id="no-match"),
    ],
)
def test_linux_matching(path: str, expected: str | None) -> None:
    assert rule_id("linux", PurePosixPath(path)) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(r"C:\u\Microsoft\Windows\Explorer\thumbcache_96.db", "thumbcache", id="both"),
        pytest.param(r"C:\u\MICROSOFT\windows\explorer\THUMBCACHE_96.DB", "thumbcache", id="case"),
        pytest.param(r"C:\u\Microsoft\Windows\Explorer\other.db", None, id="dir-without-file"),
        pytest.param(r"C:\u\Downloads\thumbcache_96.db", None, id="file-without-dir"),
        pytest.param(r"C:\u\__PyCache__\m.pyc", "pycache", id="case-insensitive"),
        pytest.param(r"C:\tmp\a.bin", None, id="platform-filtered"),
    ],
)
def test_windows_matching(path: str, expected: str | None) -> None:
    assert rule_id("windows", PureWindowsPath(path)) == expected


def test_match_carries_category_and_description() -> None:
    path = PurePosixPath("/home/a/__pycache__/m.pyc")

    assert classifier("linux").classify(path) == JunkMatch(
        path=path, rule_id="pycache", category=JunkCategory.CACHE, description="Python bytecode"
    )


def test_filesystem_root_is_not_junk() -> None:
    assert classifier("linux").classify(PurePosixPath("/")) is None


def test_relative_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="absolute"):
        classifier("linux").classify(PurePosixPath("a/b.tmp"))


# --- rule validation ---------------------------------------------------------------------------

BASE = 'id = "r"\ncategory = "cache"\ndescription = "d"\n'


@pytest.mark.parametrize(
    ("body", "message"),
    [
        pytest.param('category = "cache"\ndescription = "d"\ndirs = ["a"]', "id", id="no-id"),
        pytest.param('id = "r"\ndescription = "d"\ndirs = ["a"]', "category", id="no-category"),
        pytest.param('id = "r"\ncategory = "cache"\ndirs = ["a"]', "description", id="no-desc"),
        pytest.param(BASE + 'category2 = "x"\ndirs = ["a"]', "unknown key", id="unknown-key"),
        pytest.param(BASE.replace("cache", "nope") + 'dirs = ["a"]', "category", id="bad-cat"),
        pytest.param(BASE, "dirs or files", id="no-patterns"),
        pytest.param(BASE + "dirs = []\nfiles = []", "dirs or files", id="empty-patterns"),
        pytest.param(BASE + 'dirs = ["a//b"]', "empty segment", id="empty-segment"),
        pytest.param(BASE + 'dirs = ["a/../b"]', r"'\.\.'", id="dotdot"),
        pytest.param(BASE + 'files = ["a/b.tmp"]', "file pattern", id="slash-in-file"),
        pytest.param(BASE + 'files = [""]', "file pattern", id="empty-file-pattern"),
        pytest.param(BASE + 'dirs = "a"', "list of strings", id="not-a-list"),
        pytest.param(BASE + "dirs = [1]", "list of strings", id="not-strings"),
        pytest.param(BASE + 'dirs = ["a"]\nplatforms = ["beos"]', "platform", id="bad-platform"),
    ],
)
def test_invalid_rule_is_rejected(body: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_rules("[[rule]]\n" + body)


def test_duplicate_rule_ids_are_rejected() -> None:
    rule = "[[rule]]\n" + BASE + 'dirs = ["a"]\n'

    with pytest.raises(ValueError, match="duplicate"):
        load_rules(rule + rule)


def test_rules_without_rule_table_are_rejected() -> None:
    with pytest.raises(ValueError, match=r"\[\[rule\]\]"):
        load_rules('title = "x"')


# --- packaged default rules --------------------------------------------------------------------

LOCAL = r"C:\Users\a\AppData\Local"

DEFAULT_EXAMPLES: list[tuple[Platform, str, str | None]] = [
    ("linux", "/home/a/proj/__pycache__/m.cpython-313.pyc", "python-bytecode"),
    ("linux", "/home/a/proj/.pytest_cache/v/cache/nodeids", "tool-caches"),
    ("linux", "/home/a/proj/.mypy_cache/3.13/x.json", "tool-caches"),
    ("linux", "/home/a/.cache/pip/http/abc", "user-cache-dir"),
    ("darwin", "/Users/a/Library/Caches/com.app/x", "macos-library-caches"),
    ("windows", LOCAL + r"\Google\Chrome\User Data\Default\Cache\f_1", "chromium-cache"),
    ("windows", LOCAL + r"\Microsoft\Edge\User Data\Profile 1\Code Cache\js\x", "chromium-cache"),
    ("windows", LOCAL + r"\Mozilla\Firefox\Profiles\x.default\cache2\entries\A", "firefox-cache"),
    ("windows", LOCAL + r"\Microsoft\Windows\INetCache\IE\x.htm", "inet-cache"),
    ("windows", LOCAL + r"\Temp\x.log", "windows-user-temp"),
    ("linux", "/tmp/x.bin", "posix-temp"),
    ("linux", "/var/tmp/x.bin", "posix-temp"),
    ("linux", "/home/a/Downloads/draft.tmp", "temp-files"),
    ("windows", LOCAL + r"\Microsoft\Windows\Explorer\thumbcache_256.db", "windows-thumbcache"),
    ("windows", r"C:\Users\a\Pictures\Thumbs.db", "thumbs-db"),
    ("darwin", "/Users/a/Pictures/.DS_Store", "ds-store"),
    ("linux", "/media/usb/.DS_Store", "ds-store"),
    ("windows", LOCAL + r"\CrashDumps\app.exe.1234.dmp", "crash-dumps"),
    # Negatives: look like junk but are not (or are live).
    ("windows", r"C:\Users\a\Documents\cache\report.docx", None),
    ("linux", "/home/a/proj/tmp/data.csv", None),
    ("windows", r"C:\Users\a\Documents\~$report.docx", None),
    ("linux", "/home/a/proj/node_modules/x/index.js", None),
    ("windows", LOCAL + r"\Google\Chrome\User Data\Default\Network\Cookies", None),
    ("linux", "/home/a/Downloads/movie.part", None),
]


def flavor(platform: Platform) -> type[PurePath]:
    return PureWindowsPath if platform == "windows" else PurePosixPath


@pytest.mark.parametrize(("platform", "path", "expected"), DEFAULT_EXAMPLES)
def test_default_rules_examples(platform: Platform, path: str, expected: str | None) -> None:
    match = JunkClassifier(default_rules(), platform=platform).classify(flavor(platform)(path))

    assert (match.rule_id if match else None) == expected


def test_every_default_rule_has_an_example() -> None:
    covered = {expected for _, _, expected in DEFAULT_EXAMPLES}

    assert {rule.id for rule in default_rules()} <= covered


# --- a directory: the folder organize is asked to sort (decision 0012, item 8) -----------------

DIRECTORY_EXAMPLES: list[tuple[Platform, str, str | None]] = [
    ("linux", "/home/a/.cache", "user-cache-dir"),  # the directory a rule names
    ("linux", "/home/a/.cache/thumbnails/large", "user-cache-dir"),  # and below it
    ("linux", "/home/a/proj/__pycache__", "python-bytecode"),
    ("linux", "/var/tmp/build", "posix-temp"),  # anchored at the root
    ("windows", LOCAL + r"\TEMP\setup", "windows-user-temp"),  # any case on Windows
    # A rule that names files too matches the directory it looks in: the folder holds them.
    ("windows", LOCAL + r"\Microsoft\Windows\Explorer", "windows-thumbcache"),
    # File rules alone never match a directory, whatever it is called.
    ("linux", "/home/a/Downloads", None),
    ("linux", "/home/a/backup.tmp", None),
    ("linux", "/home/a/Thumbs.db", None),
    ("linux", "/home/a/proj/tmp", None),
    ("linux", "/", None),
]


@pytest.mark.parametrize(("platform", "path", "expected"), DIRECTORY_EXAMPLES)
def test_a_directory_is_classified_by_the_directories_of_the_rules(
    platform: Platform, path: str, expected: str | None
) -> None:
    classifier = JunkClassifier(default_rules(), platform=platform)
    match = classifier.classify_directory(flavor(platform)(path))

    assert (match.rule_id if match else None) == expected


def test_a_relative_directory_is_rejected() -> None:
    classifier = JunkClassifier(default_rules(), platform="linux")
    with pytest.raises(ValueError, match="absolute"):
        classifier.classify_directory(PurePosixPath("proj/__pycache__"))
