"""Junk heuristics: rules are data (TOML), the engine only interprets them.

Rule semantics:
* ``dirs``: path patterns ("a/b/*/c", segments are globs) that must appear as *consecutive*
  parent directories; a leading "/" anchors the pattern at the filesystem root.
* ``files``: file-name globs.
* A rule with both matches only when both match. The first matching rule (file order) wins.
* Matching is case-insensitive on Windows and macOS, case-sensitive on Linux.
"""

from fnmatch import fnmatchcase
from pathlib import PurePath, PurePosixPath, PureWindowsPath

import pytest

from kresorter.core import heuristics
from kresorter.core.heuristics import (
    JunkCategory,
    JunkClassifier,
    JunkMatch,
    JunkRule,
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
LOCALLOW = r"C:\Users\a\AppData\LocalLow"
CHROME = LOCAL + r"\Google\Chrome\User Data"

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
    # [0018.20] A browser's cache, on Linux under ~/.cache, Opera's on Windows.
    ("linux", "/home/a/.cache/google-chrome/Default/Cache/Cache_Data/f_1", "browser-caches"),
    ("linux", "/home/a/.cache/chromium/Default/Code Cache/js/x", "browser-caches"),
    ("linux", "/home/a/.cache/mozilla/firefox/x.default/cache2/entries/A", "browser-caches"),
    ("linux", "/home/a/.cache/BraveSoftware/Brave-Browser/Default/Cache/x", "browser-caches"),
    ("linux", "/home/a/.cache/microsoft-edge/Default/Cache/x", "browser-caches"),
    ("linux", "/home/a/.cache/opera/Cache/x", "browser-caches"),
    ("linux", "/home/a/.cache/vivaldi/Default/Cache/x", "browser-caches"),
    ("linux", "/home/a/.cache/yandex-browser/Default/Cache/x", "browser-caches"),
    ("linux", "/home/a/snap/firefox/common/.cache/mozilla/firefox/x/cache2/A", "browser-caches"),
    ("windows", LOCAL + r"\Opera Software\Opera Stable\Cache\Cache_Data\f_1", "opera-cache"),
    ("windows", LOCAL + r"\Opera Software\Opera GX Stable\Cache\x", "opera-cache"),
    # The freedesktop thumbnails under ~/.cache are thumbnails, not a cache of a program.
    ("linux", "/home/a/.cache/thumbnails/large/0a1b.png", "xdg-thumbnails"),
    ("windows", LOCAL + r"\Temp\x.log", "windows-user-temp"),
    ("linux", "/tmp/x.bin", "posix-temp"),
    ("linux", "/var/tmp/x.bin", "posix-temp"),
    ("linux", "/home/a/Downloads/draft.tmp", "temp-files"),
    ("windows", LOCAL + r"\Microsoft\Windows\Explorer\thumbcache_256.db", "windows-thumbcache"),
    ("windows", r"C:\Users\a\Pictures\Thumbs.db", "thumbs-db"),
    ("darwin", "/Users/a/Pictures/.DS_Store", "ds-store"),
    ("linux", "/media/usb/.DS_Store", "ds-store"),
    ("windows", LOCAL + r"\CrashDumps\app.exe.1234.dmp", "crash-dumps"),
    # [0020.14] The graphics drivers' shader caches, the browsers', Windows' error reports.
    ("windows", LOCAL + r"\NVIDIA\DXCache\1a2b.nvph", "gpu-shader-caches"),
    ("windows", LOCAL + r"\NVIDIA\GLCache\x\y.bin", "gpu-shader-caches"),
    ("windows", LOCALLOW + r"\NVIDIA\PerDriverVersion\DXCache\x.nvph", "gpu-shader-caches"),
    ("windows", LOCALLOW + r"\NVIDIA\PerDriverVersion\GLCache\x\y.bin", "gpu-shader-caches"),
    ("windows", LOCAL + r"\AMD\DxCache\x.parc", "gpu-shader-caches"),
    ("windows", LOCAL + r"\AMD\DxcCache\x.parc", "gpu-shader-caches"),
    ("windows", LOCAL + r"\AMD\GLCache\x.bin", "gpu-shader-caches"),
    ("windows", LOCAL + r"\AMD\VkCache\x.parc", "gpu-shader-caches"),
    ("windows", LOCALLOW + r"\Intel\ShaderCache\x.bin", "gpu-shader-caches"),
    ("windows", LOCAL + r"\D3DSCache\x\y.idx", "gpu-shader-caches"),
    ("windows", CHROME + r"\ShaderCache\data_0", "chromium-shader-caches"),
    ("windows", CHROME + r"\GrShaderCache\data_1", "chromium-shader-caches"),
    ("windows", CHROME + r"\GraphiteDawnCache\data_0", "chromium-shader-caches"),
    ("windows", CHROME + r"\Default\DawnCache\data_0", "chromium-shader-caches"),
    ("windows", CHROME + r"\Profile 1\DawnGraphiteCache\data_1", "chromium-shader-caches"),
    ("windows", CHROME + r"\Default\DawnWebGPUCache\index", "chromium-shader-caches"),
    (
        "windows",
        LOCAL + r"\Microsoft\Windows\WER\ReportArchive\AppCrash_x\Report.wer",
        "windows-error-reports",
    ),
    (
        "windows",
        LOCAL + r"\Microsoft\Windows\WER\ReportQueue\AppHang_x\Report.wer",
        "windows-error-reports",
    ),
    ("windows", LOCAL + r"\Microsoft\Windows\WER\Temp\x.xml", None),
    ("windows", LOCAL + r"\NVIDIA Corporation\NvBackend\x.json", None),
    # Negatives: look like junk but are not (or are live).
    ("windows", r"C:\Users\a\Documents\cache\report.docx", None),
    ("linux", "/home/a/proj/tmp/data.csv", None),
    ("windows", r"C:\Users\a\Documents\~$report.docx", None),
    ("linux", "/home/a/proj/node_modules/x/index.js", None),
    ("windows", LOCAL + r"\Google\Chrome\User Data\Default\Network\Cookies", None),
    # [0018.20] A browser's site data is never junk: a web app's offline data, its storage.
    ("windows", LOCAL + r"\Google\Chrome\User Data\Default\Service Worker\CacheStorage\x", None),
    ("windows", LOCAL + r"\Google\Chrome\User Data\Default\IndexedDB\x\000003.log", None),
    ("windows", LOCAL + r"\Google\Chrome\User Data\Default\Local Storage\leveldb\x", None),
    ("linux", "/home/a/.config/google-chrome/Default/Service Worker/CacheStorage/x", None),
    ("linux", "/home/a/.mozilla/firefox/x.default/storage/default/x/idb/1.sqlite", None),
    ("linux", "/home/a/Downloads/movie.part", None),
]


def flavor(platform: Platform) -> type[PurePath]:
    return PureWindowsPath if platform == "windows" else PurePosixPath


@pytest.mark.parametrize(("platform", "path", "expected"), DEFAULT_EXAMPLES)
def test_default_rules_examples(platform: Platform, path: str, expected: str | None) -> None:
    match = JunkClassifier(default_rules(), platform=platform).classify(flavor(platform)(path))

    assert (match.rule_id if match else None) == expected


@pytest.mark.parametrize(
    ("rule", "category"),
    [
        ("gpu-shader-caches", JunkCategory.CACHE),
        ("chromium-shader-caches", JunkCategory.BROWSER_CACHE),
        ("windows-error-reports", JunkCategory.CRASH_DUMP),
    ],
)
def test_the_shader_caches_and_error_reports_are_of_their_kind(
    rule: str, category: JunkCategory
) -> None:
    # [0020.14] a driver's is rebuilt by it; a browser's is a browser's cache, for review
    found = {r.id: r for r in default_rules()}[rule]
    assert (found.category, found.platforms) == (category, frozenset({"windows"}))


def test_every_default_rule_has_an_example() -> None:
    covered = {expected for _, _, expected in DEFAULT_EXAMPLES}

    assert {rule.id for rule in default_rules()} <= covered


# --- a directory: the folder organize is asked to sort (decision 0012, item 8) -----------------

DIRECTORY_EXAMPLES: list[tuple[Platform, str, str | None]] = [
    ("linux", "/home/a/.cache", "user-cache-dir"),  # the directory a rule names
    ("linux", "/home/a/.cache/pip/http", "user-cache-dir"),  # and below it
    ("linux", "/home/a/.cache/thumbnails/large", "xdg-thumbnails"),  # a rule before it
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


@pytest.mark.parametrize(
    ("platform", "path", "category"),
    [
        ("windows", LOCAL + r"\Google\Chrome\User Data\Default\Cache\f_1", "browser_cache"),
        ("windows", LOCAL + r"\Mozilla\Firefox\Profiles\x\cache2\entries\A", "browser_cache"),
        ("windows", LOCAL + r"\Microsoft\Windows\INetCache\IE\x.htm", "browser_cache"),
        ("windows", LOCAL + r"\Opera Software\Opera Stable\Cache\x", "browser_cache"),
        ("linux", "/home/a/.cache/google-chrome/Default/Cache/x", "browser_cache"),
        ("linux", "/home/a/.cache/pip/http/abc", "cache"),
        ("linux", "/home/a/.cache/thumbnails/normal/x.png", "thumbnails"),
    ],
)
def test_a_browser_s_cache_is_a_category_of_its_own(
    platform: Platform, path: str, category: str
) -> None:
    # [0018.20] The rules of a browser's cache come before the others.
    match = JunkClassifier(default_rules(), platform=platform).classify(flavor(platform)(path))
    assert match is not None
    assert match.category == category


# --- once per directory (decision 0018, item 13) -------------------------------------------------


def reference(rules: tuple[JunkRule, ...], platform: Platform, path: PurePath) -> str | None:
    """The rule every path got before: each rule's directories and files asked for each file,
    every segment a glob."""
    fold = str if platform == "linux" else str.casefold
    parts = tuple(fold(p) for p in flavor(platform)(path).parts[1:])
    if not parts:
        return None
    dirs, name = parts[:-1], parts[-1]
    for rule in rules:
        if platform not in rule.platforms:
            continue
        patterns = [([fold(s) for s in p.segments], p.anchored) for p in rule.dirs]
        dirs_ok = not patterns or any(
            any(
                all(fnmatchcase(dirs[i + j], s) for j, s in enumerate(segments))
                for i in (
                    range(min(1, len(dirs) - len(segments) + 1))
                    if anchored
                    else range(len(dirs) - len(segments) + 1)
                )
            )
            for segments, anchored in patterns
        )
        files_ok = not rule.files or any(fnmatchcase(name, fold(f)) for f in rule.files)
        if dirs_ok and files_ok:
            return rule.id
    return None


def sample(glob: str) -> str:
    """A text the glob matches: ``*`` as ``x``, ``?`` as ``q`` (no default rule has a class)."""
    assert "[" not in glob
    return glob.replace("*", "x").replace("?", "q")


def corpus(platform: Platform) -> list[PurePath]:
    """Paths every default rule matches and nearly matches, in more than one case, several
    files in each directory, as a scan meets them; an anchored rule's at the root."""
    home = flavor(platform)(r"C:\Users\a" if platform == "windows" else "/home/a")
    rules = default_rules()
    folders = [home, home / "proj", home / "Downloads" / "sub"]
    for rule in rules:
        for pattern in rule.dirs:
            segments = [sample(s) for s in pattern.segments]
            base = flavor(platform)(home.anchor) if pattern.anchored else home
            folders += [base.joinpath(*segments), base.joinpath(*segments, "deeper")]
            folders += [base.joinpath(*segments[:-1]), base.joinpath("x", *segments)]
            folders.append(base.joinpath(*(s.upper() for s in segments)))
    names = ["a.txt", "report.docx", "x.QQQ"]
    for rule in rules:
        names += [sample(f) for f in rule.files] + [sample(f).upper() for f in rule.files]
    return [folder / name for folder in folders for name in names]


@pytest.mark.parametrize("platform", ["linux", "windows", "darwin"])
def test_every_path_gets_the_rule_it_got_before(platform: Platform) -> None:
    # [0018.13] Rules matched once per directory, a literal segment by equality: the same rule.
    classifier = JunkClassifier(default_rules(), platform=platform)
    paths = corpus(platform)
    assert len(paths) > 1000
    got = [(match.rule_id if (match := classifier.classify(p)) else None) for p in paths]
    assert got == [reference(default_rules(), platform, p) for p in paths]
    assert {rule for rule in got if rule} == {
        rule.id for rule in default_rules() if platform in rule.platforms
    }


def test_a_directory_s_rules_are_matched_once_and_its_files_by_their_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [0018.13] Per file only the file-name globs; a segment without *, ? or [ by equality.
    rules = load_rules(
        '[[rule]]\nid = "r"\ncategory = "cache"\ndescription = "d"\n'
        'dirs = ["build/*cache*"]\nfiles = ["*.tmp"]\n'
    )
    globbed: list[tuple[str, str]] = []

    def counting(name: str, pattern: str) -> bool:
        globbed.append((name, pattern))
        return fnmatchcase(name, pattern)

    monkeypatch.setattr(heuristics, "fnmatchcase", counting)
    classifier = JunkClassifier(rules, platform="linux")
    folder = PurePosixPath("/x/build/cachedir")
    found = [classifier.classify(folder / name) for name in ("a.tmp", "b.tmp", "c.txt")]
    assert [match.rule_id if match else None for match in found] == ["r", "r", None]
    assert globbed == [
        ("cachedir", "*cache*"),
        ("a.tmp", "*.tmp"),
        ("b.tmp", "*.tmp"),
        ("c.txt", "*.tmp"),
    ]
