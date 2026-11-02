"""The window's two languages (decision 0014, items 28-31). No Qt is needed here."""

from enum import StrEnum

import pytest

from safeclean.analysis.score import Evidence, Level
from safeclean.autostart.journal import ChangeRefusal, ChangeState
from safeclean.autostart.models import Scope, Source
from safeclean.core.models import SkipReason
from safeclean.core.policy import BlockReason
from safeclean.core.preflight import RefusalReason
from safeclean.llm.failure import Unavailable
from safeclean.organize.folders import FolderReason
from safeclean.organize.journal import BatchKind, BatchState
from safeclean.organize.planner import StayReason
from safeclean.organize.platforms import Blocker
from safeclean.organize.undo import UndoReason
from safeclean.quarantine.service import PurgeRefusal, RestoreRefusal
from safeclean.storage.pending import Domain
from safeclean.storage.session import SessionFailure
from safeclean.text import format_size
from safeclean.ui.i18n import (
    CATALOG,
    LABELS,
    LANGUAGES,
    PLURALS,
    Translator,
    catalog_problems,
    label_problems,
    language_for,
    placeholders,
    plural_problems,
    russian_form,
)
from safeclean.ui.settings import Unused

SHOWN: tuple[type[StrEnum], ...] = (
    Level,
    Evidence,
    RefusalReason,
    BlockReason,
    SkipReason,
    RestoreRefusal,
    PurgeRefusal,
    StayReason,
    FolderReason,
    UndoReason,
    Blocker,
    BatchKind,
    BatchState,
    Source,
    Scope,
    ChangeState,
    ChangeRefusal,
    Domain,
    Unavailable,
    SessionFailure,
    Unused,
)

# --- the rules, on made-up catalogs [0014.28] ----------------------------------------------------


def test_the_placeholders_of_a_text() -> None:
    # [0014.28]
    assert placeholders("Moved {n} of {total} from {folder}") == {"n", "total", "folder"}
    assert placeholders("Nothing {{here}}") == set()
    assert placeholders("") == set()


def test_a_missing_language_an_empty_text_and_other_placeholders_are_found() -> None:
    # [0014.28]
    made_up = {
        "ok": {"en": "Scan {folder}", "ru": "Сканировать {folder}"},
        "no.ru": {"en": "Scan"},
        "empty": {"en": "Scan", "ru": ""},
        "other": {"en": "Scan {folder}", "ru": "Сканировать {path}"},
        "extra": {"en": "Scan", "ru": "Сканировать", "de": "Scannen"},
    }
    assert catalog_problems(made_up) == ["empty", "extra", "no.ru", "other"]


def test_counts_need_every_form_of_each_language_with_the_number() -> None:
    # [0014.29]
    made_up: dict[str, dict[str, tuple[str, ...]]] = {
        "ok": {"en": ("{n} file", "{n} files"), "ru": ("{n} файл", "{n} файла", "{n} файлов")},
        "short": {"en": ("{n} file", "{n} files"), "ru": ("{n} файл", "{n} файла")},
        "no.n": {"en": ("one file", "{n} files"), "ru": ("{n} файл", "{n} файла", "{n} файлов")},
        "other": {"en": ("{n} file", "{n} files"), "ru": ("{n} {x}", "{n} файла", "{n} файлов")},
    }
    assert plural_problems(made_up) == ["no.n", "other", "short"]


def test_a_value_without_a_label_is_found() -> None:
    # [0014.31]
    class Made(StrEnum):
        ONE = "one"
        TWO = "two"

    labels = {Made: {"one": {"en": "One", "ru": "Один"}}}
    assert label_problems(labels, (Made,)) == ["Made.two"]
    both = {Made: {"one": {"en": "One", "ru": "Один"}, "two": {"en": "One", "ru": "Два"}}}
    assert label_problems(both, (Made,)) == ["Made: en labels repeat"]


# --- the catalog of the window -------------------------------------------------------------------


def test_every_text_is_in_both_languages() -> None:
    # [0014.28]
    assert LANGUAGES == ("en", "ru")
    assert catalog_problems(CATALOG) == []
    assert CATALOG  # the rule reads something


def test_every_count_has_each_language_s_forms() -> None:
    # [0014.29]
    assert plural_problems(PLURALS) == []
    assert "file" in PLURALS


@pytest.mark.parametrize(
    ("n", "form"),
    [
        (0, 2),
        (1, 0),
        (2, 1),
        (4, 1),
        (5, 2),
        (11, 2),
        (12, 2),
        (14, 2),
        (21, 0),
        (22, 1),
        (101, 0),
        (111, 2),
        (112, 2),
        (1004, 1),
    ],
)
def test_the_russian_form_of_a_count(n: int, form: int) -> None:
    # [0014.29] one, few, many
    assert russian_form(n) == form


def test_counts_in_russian() -> None:
    # [0014.29]
    count = Translator("ru").count
    assert [count("file", n) for n in (1, 2, 5, 11, 21, 22, 111)] == [
        "1 файл",
        "2 файла",
        "5 файлов",
        "11 файлов",
        "21 файл",
        "22 файла",
        "111 файлов",
    ]


def test_counts_in_english() -> None:
    # [0014.29]
    count = Translator("en").count
    assert [count("file", n) for n in (0, 1, 2, 21)] == ["0 files", "1 file", "2 files", "21 files"]


@pytest.mark.parametrize(
    ("setting", "system", "language"),
    [
        ("en", "ru_RU", "en"),
        ("ru", "en_US", "ru"),
        ("system", "ru_RU", "ru"),
        ("system", "ru_UA", "ru"),
        ("system", "ru", "ru"),
        ("system", "ru-RU", "ru"),
        ("system", "en_US", "en"),
        ("system", "de_DE", "en"),
        ("system", "uk_UA", "en"),
        ("system", "C", "en"),
        ("system", "", "en"),
    ],
)
def test_which_language(setting: str, system: str, language: str) -> None:
    # [0014.30]
    assert language_for(setting, system) == language


def test_a_text_takes_its_values_as_they_are() -> None:
    # [0014.28] [0014.31] a path with braces is not read as a placeholder
    folder = "/home/a/{n} {{x}}"
    for language in LANGUAGES:
        assert folder in Translator(language).text("overview.folder", folder=folder)


def test_every_value_shown_has_a_label_in_both_languages() -> None:
    # [0014.31]
    assert label_problems(LABELS, SHOWN) == []
    assert Translator("en").label(Level.REVIEW) == "Review"
    assert Translator("ru").label(Level.REVIEW) == "Проверить"


def test_an_unknown_key_is_an_error() -> None:
    # [0014.28] a key the catalog lacks is a mistake of the window, never shown as a key
    with pytest.raises(KeyError):
        Translator("en").text("no.such.key")


@pytest.mark.parametrize(
    ("n", "english", "russian"),
    [
        (0, "0 B", "0 Б"),
        (8, "8 B", "8 Б"),
        (1023, "1023 B", "1023 Б"),
        (1024, "1.0 KiB", "1,0 КиБ"),
        (1536, "1.5 KiB", "1,5 КиБ"),
        (10 * 1024**2, "10.0 MiB", "10,0 МиБ"),
        (3 * 1024**3, "3.0 GiB", "3,0 ГиБ"),
        (5 * 1024**5, "5120.0 TiB", "5120,0 ТиБ"),
    ],
)
def test_sizes_in_each_language(n: int, english: str, russian: str) -> None:
    # [0014.28] English as the CLI writes them; Russian with its units and decimal comma.
    assert Translator("en").size(n) == english == format_size(n)
    assert Translator("ru").size(n) == russian
