"""Organize's categories in the window's language, their directories by their names on disk
(decision 0014, item 44). No Qt is needed here."""

from kresorter.organize.categories import default_table
from kresorter.ui.i18n import LANGUAGES, Translator
from kresorter.ui.labels import CATEGORIES

NAMES = default_table().names


def test_every_category_of_the_table_and_no_other_has_a_label_in_both_languages() -> None:
    # [0014.44]
    assert sorted(CATEGORIES) == sorted(NAMES)
    assert all(sorted(CATEGORIES[name]) == sorted(LANGUAGES) for name in NAMES)
    assert all(text for name in NAMES for text in CATEGORIES[name].values())


def test_no_two_labels_of_a_language_are_the_same() -> None:
    # [0014.44]
    for language in LANGUAGES:
        shown = [Translator(language).category(name) for name in NAMES]
        assert len(set(shown)) == len(shown)


def test_the_english_label_is_the_name_on_disk() -> None:
    # [0014.44]
    assert [Translator("en").category(name) for name in NAMES] == list(NAMES)


def test_the_russian_labels() -> None:
    # [0014.44]
    ru = Translator("ru")
    assert [ru.category(name) for name in NAMES] == [
        "Изображения",
        "Видео",
        "Аудио",
        "Документы",
        "Архивы",
        "Установщики",
    ]


def test_a_name_without_a_label_is_shown_as_it_is() -> None:
    # [0014.44]
    for language in LANGUAGES:
        assert Translator(language).category("Fonts") == "Fonts"
