"""The window's settings file (decision 0014, items 35-36).

Only ``settings.json`` in the data directory: ``language`` and ``include_machine``, written by
``save`` alone, after the data directory is checked, through a temporary file renamed over it,
private. ``load`` writes nothing; a missing file means the defaults, a broken one the defaults
and why it was not used; unknown keys are ignored.
"""

import dataclasses
import json
import stat
from pathlib import Path

import pytest

from kresorter.core.scanner import ScanContext
from kresorter.storage.session import SessionFailure
from kresorter.ui.settings import (
    DEFAULTS,
    LANGUAGE_SETTINGS,
    SETTINGS_NAME,
    TEMP_NAME,
    LanguageSetting,
    Loaded,
    Settings,
    Unused,
    load,
    save,
)
from support.cli import scan_context
from support.host import as_kept, posix_only, record_opens


@pytest.fixture
def context(tmp_path: Path, zone: Path, data_dir: Path) -> ScanContext:
    return scan_context(tmp_path, zone, data_dir)


def _listing(root: Path) -> dict[str, bytes | None]:
    """Every path under ``root``, with a file's bytes."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in sorted(root.rglob("*"))
    }


def _write(data_dir: Path, content: bytes) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / SETTINGS_NAME
    path.write_bytes(content)
    return path


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# --- one small file [0014.35] --------------------------------------------------------------------


def test_the_settings_are_the_language_and_the_machine_scope() -> None:
    # [0014.35] Nothing else is remembered: no finding, path, plan or explanation.
    assert [field.name for field in dataclasses.fields(Settings)] == [
        "language",
        "include_machine",
    ]
    assert Settings() == DEFAULTS == Settings(language="system", include_machine=False)
    assert LANGUAGE_SETTINGS == ("system", "en", "ru")
    assert (SETTINGS_NAME, TEMP_NAME) == ("settings.json", "settings.json.tmp")


@pytest.mark.parametrize("language", ["system", "en", "ru"])
@pytest.mark.parametrize("include_machine", [False, True])
def test_what_is_saved_is_loaded(
    context: ScanContext, data_dir: Path, language: LanguageSetting, include_machine: bool
) -> None:
    # [0014.35]
    settings = Settings(language=language, include_machine=include_machine)
    assert save(context, settings) is None
    assert load(context) == Loaded(settings)
    saved = json.loads((data_dir / SETTINGS_NAME).read_text(encoding="utf-8"))
    assert saved == {"language": language, "include_machine": include_machine}


def test_saving_makes_the_data_directory_private_and_the_file_alone_in_it(
    context: ScanContext, data_dir: Path
) -> None:
    # [0014.35]
    assert not data_dir.exists()
    assert save(context, Settings(language="ru")) is None
    assert _mode(data_dir) == as_kept(0o700, directory=True)
    assert _mode(data_dir / SETTINGS_NAME) == as_kept(0o600)
    assert sorted(path.name for path in data_dir.iterdir()) == [SETTINGS_NAME]


@posix_only("on Windows a file open elsewhere cannot be replaced")
def test_the_file_is_replaced_by_a_renamed_temporary_file(
    context: ScanContext, data_dir: Path
) -> None:
    # [0014.35] A new file each time, never the old one rewritten: a reader sees one or the
    # other whole.
    assert save(context, Settings(language="en")) is None
    before = (data_dir / SETTINGS_NAME).stat().st_ino
    kept = (data_dir / SETTINGS_NAME).open("rb")  # the old file stays open under its inode
    try:
        assert save(context, Settings(language="ru")) is None
        assert (data_dir / SETTINGS_NAME).stat().st_ino != before
        assert json.loads(kept.read())["language"] == "en"
    finally:
        kept.close()
    assert load(context) == Loaded(Settings(language="ru"))
    assert sorted(path.name for path in data_dir.iterdir()) == [SETTINGS_NAME]


def test_the_file_is_written_as_bytes(
    context: ScanContext, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0015.20] on Windows too: the file is the JSON written, its \n not made \r\n
    opens = record_opens(monkeypatch)
    assert save(context, Settings(language="ru")) is None
    assert opens.in_binary(TEMP_NAME)
    assert (data_dir / SETTINGS_NAME).read_bytes().count(b"\r") == 0


def test_a_temporary_file_left_behind_is_overwritten(context: ScanContext, data_dir: Path) -> None:
    # [0014.35] One temporary name: what a crash left is written over, never piled up.
    data_dir.mkdir(parents=True)
    (data_dir / TEMP_NAME).write_bytes(b'{"language": "en", "include_machine": true, "x": 1}' * 9)
    (data_dir / TEMP_NAME).chmod(0o644)
    assert save(context, Settings(language="ru")) is None
    assert sorted(path.name for path in data_dir.iterdir()) == [SETTINGS_NAME]
    assert _mode(data_dir / SETTINGS_NAME) == as_kept(0o600)
    assert load(context) == Loaded(Settings(language="ru"))


def test_nothing_is_written_where_the_data_directory_must_not_be(
    tmp_path: Path, zone: Path
) -> None:
    # [0014.35] The data directory is checked first (0009): inside a scan zone, no file.
    inside = zone / "kresorter"
    context = scan_context(tmp_path, zone, inside)
    before = _listing(tmp_path)
    failed = save(context, Settings(language="ru"))
    assert failed is not None
    assert failed.failure is SessionFailure.DATA_DIR
    assert str(inside) in failed.detail
    assert _listing(tmp_path) == before


def test_a_write_that_fails_is_a_value(context: ScanContext, data_dir: Path) -> None:
    # [0014.35]
    (data_dir / SETTINGS_NAME).mkdir(parents=True)  # nothing can be renamed over a directory
    failed = save(context, Settings(language="ru"))
    assert failed is not None
    assert failed.failure is SessionFailure.DATA_DIR_OS
    assert failed.detail


def test_a_data_directory_that_cannot_be_made_is_a_value(
    tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0014.35]
    data_dir.parent.mkdir(parents=True)
    data_dir.write_bytes(b"not a directory")
    failed = save(scan_context(tmp_path, zone, data_dir), Settings())
    assert failed is not None
    assert failed.failure is SessionFailure.DATA_DIR_OS
    assert data_dir.read_bytes() == b"not a directory"


# --- a broken file is not trusted [0014.36] ------------------------------------------------------


def test_a_missing_file_means_the_defaults(context: ScanContext, data_dir: Path) -> None:
    # [0014.36] Loading makes nothing, not even the data directory.
    assert load(context) == Loaded(DEFAULTS)
    assert not data_dir.exists()


def test_an_unreadable_file_means_the_defaults(context: ScanContext, data_dir: Path) -> None:
    # [0014.36]
    (data_dir / SETTINGS_NAME).mkdir(parents=True)
    loaded = load(context)
    assert (loaded.settings, loaded.unused) == (DEFAULTS, Unused.UNREADABLE)
    assert loaded.detail


@pytest.mark.parametrize(
    "content",
    [b"", b"{", b"{'language': 'ru'}", b"\xff\xfe\xfa", b"NaN!", b"[" * 100_000],
    ids=["empty", "open", "quotes", "not utf-8", "after", "too deep"],
)
def test_invalid_json_means_the_defaults(
    context: ScanContext, data_dir: Path, content: bytes
) -> None:
    # [0014.36]
    _write(data_dir, content)
    loaded = load(context)
    assert (loaded.settings, loaded.unused) == (DEFAULTS, Unused.NOT_JSON)
    assert loaded.detail


@pytest.mark.parametrize("content", [b"[]", b'"ru"', b"null", b"1", b"true"])
def test_a_file_that_is_not_an_object_means_the_defaults(
    context: ScanContext, data_dir: Path, content: bytes
) -> None:
    # [0014.36]
    _write(data_dir, content)
    assert load(context) == Loaded(DEFAULTS, Unused.NOT_AN_OBJECT, "")


@pytest.mark.parametrize(
    ("value", "detail"),
    [
        ({"language": "de"}, 'language="de"'),
        ({"language": "RU"}, 'language="RU"'),
        ({"language": 1}, "language=1"),
        ({"language": None}, "language=null"),
        ({"language": ["ru"]}, 'language=["ru"]'),
        ({"language": "ru", "include_machine": "yes"}, 'include_machine="yes"'),
        ({"language": "ru", "include_machine": 1}, "include_machine=1"),
        ({"include_machine": 0}, "include_machine=0"),
        ({"include_machine": None}, "include_machine=null"),
    ],
)
def test_a_value_of_the_wrong_type_or_unknown_means_every_default(
    context: ScanContext, data_dir: Path, value: object, detail: str
) -> None:
    # [0014.36] Not the other value either: the file is not used at all.
    _write(data_dir, json.dumps(value).encode())
    assert load(context) == Loaded(DEFAULTS, Unused.WRONG_VALUE, detail)


def test_unknown_keys_are_ignored(context: ScanContext, data_dir: Path) -> None:
    # [0014.36]
    content = {"language": "ru", "include_machine": True, "theme": "dark", "findings": [1]}
    _write(data_dir, json.dumps(content).encode())
    assert load(context) == Loaded(Settings(language="ru", include_machine=True))


@pytest.mark.parametrize(
    ("value", "settings"),
    [
        ({}, DEFAULTS),
        ({"language": "en"}, Settings(language="en")),
        ({"include_machine": True}, Settings(include_machine=True)),
    ],
)
def test_a_key_left_out_takes_its_default(
    context: ScanContext, data_dir: Path, value: object, settings: Settings
) -> None:
    # [0014.36]
    _write(data_dir, json.dumps(value).encode())
    assert load(context) == Loaded(settings)


@pytest.mark.parametrize(
    "content", [b"{", b"[]", b'{"language": "de"}', b'{"include_machine": "yes"}']
)
def test_a_broken_file_is_not_written_by_loading(
    context: ScanContext, data_dir: Path, content: bytes
) -> None:
    # [0014.36] It stays as it is until the user changes a setting.
    path = _write(data_dir, content)
    before = _listing(data_dir)
    assert load(context).unused is not None
    assert load(context).unused is not None
    assert _listing(data_dir) == before
    assert save(context, Settings(language="en")) is None
    assert load(context) == Loaded(Settings(language="en"))
    assert path.read_bytes() != content


# --- the zones left out (decision 0018, item 17) -------------------------------------------------


def test_the_zones_left_out_are_remembered_by_their_names(
    context: ScanContext, data_dir: Path
) -> None:
    # [0018.17] A zone's last part, never a path.
    settings = Settings(skipped_zones=("zone",))
    assert save(context, settings) is None
    assert load(context) == Loaded(settings)
    saved = json.loads((data_dir / SETTINGS_NAME).read_text(encoding="utf-8"))
    assert saved["skipped_zones"] == ["zone"]
    assert Settings().skipped_zones == ()


@pytest.mark.parametrize(
    ("value", "detail"),
    [
        ("zone", 'skipped_zones="zone"'),
        (["other"], 'skipped_zones=["other"]'),
        (["Zone"], 'skipped_zones=["Zone"]'),
        (["zone", "zone"], 'skipped_zones=["zone", "zone"]'),
        ([1], "skipped_zones=[1]"),
        (None, "skipped_zones=null"),
    ],
)
def test_a_name_of_no_zone_is_a_wrong_value(
    context: ScanContext, data_dir: Path, value: object, detail: str
) -> None:
    # [0018.17] Not the other names either: the file is not used at all.
    _write(data_dir, json.dumps({"language": "ru", "skipped_zones": value}).encode())
    assert load(context) == Loaded(DEFAULTS, Unused.WRONG_VALUE, detail)


def test_a_zone_s_path_is_a_wrong_value(context: ScanContext, data_dir: Path, zone: Path) -> None:
    # [0018.17]
    _write(data_dir, json.dumps({"skipped_zones": [str(zone)]}).encode())
    assert load(context).unused == Unused.WRONG_VALUE
