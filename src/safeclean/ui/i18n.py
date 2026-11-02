"""The window's two languages, English and Russian (decision 0014, items 28-31).

Every text is looked up by key in ``texts.CATALOG``, every count in ``texts.PLURALS`` (English:
one and other; Russian: one, few and many), every value of an enumeration the window shows in
``labels.LABELS``, every size in the units of ``texts.UNITS``. Values put into a text are
inserted as they are: paths, names, details from the system and explanations are never
translated. No Qt is needed here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from string import Formatter
from typing import Literal, TypeVar

from safeclean.ui.labels import LABELS
from safeclean.ui.texts import CATALOG, DECIMAL, PLURALS, UNITS

__all__ = [
    "CATALOG",
    "LABELS",
    "LANGUAGES",
    "PLURALS",
    "Language",
    "Translator",
    "catalog_problems",
    "label_problems",
    "language_for",
    "placeholders",
    "plural_problems",
    "russian_form",
]

Language = Literal["en", "ru"]
LANGUAGES: tuple[Language, ...] = ("en", "ru")
_FORMS: dict[str, int] = {"en": 2, "ru": 3}  # one, other; one, few, many
_SETTINGS: dict[str, Language] = {"en": "en", "ru": "ru"}
_E = TypeVar("_E", bound=StrEnum)


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(text) if name is not None}


def catalog_problems(catalog: Mapping[str, Mapping[str, str]]) -> list[str]:
    """The keys without exactly both languages, with an empty text, or whose texts differ in
    their placeholders."""
    return sorted(key for key, texts in catalog.items() if not _complete(texts.values(), texts))


def plural_problems(plurals: Mapping[str, Mapping[str, tuple[str, ...]]]) -> list[str]:
    """The counts without each language's forms, a form without ``{n}``, or other
    placeholders."""
    problems: list[str] = []
    for key, forms in plurals.items():
        every = [form for language in forms for form in forms[language]]
        sizes = all(len(forms[language]) == _FORMS.get(language) for language in forms)
        numbered = all("n" in placeholders(form) for form in every)
        if not (sizes and numbered and _complete(every, forms)):
            problems.append(key)
    return sorted(problems)


def _complete(texts: Iterable[str], languages: Mapping[str, object]) -> bool:
    found = list(texts)
    same = len({frozenset(placeholders(text)) for text in found}) == 1
    return set(languages) == set(LANGUAGES) and all(found) and same


def label_problems(
    labels: Mapping[type[_E], Mapping[str, Mapping[str, str]]],
    enums: Iterable[type[_E]],
) -> list[str]:
    """A value without a label in both languages, and an enumeration whose labels repeat."""
    problems: list[str] = []
    for enum in enums:
        known = labels.get(enum, {})
        for member in enum:
            texts = known.get(member.value, {})
            if set(texts) != set(LANGUAGES) or not all(texts.values()):
                problems.append(f"{enum.__name__}.{member.value}")
        for language in LANGUAGES:
            shown = [texts.get(language) for texts in known.values()]
            if len(set(shown)) != len(shown):
                problems.append(f"{enum.__name__}: {language} labels repeat")
    return problems


def russian_form(n: int) -> int:
    """0 one (1, 21, 101), 1 few (2-4, 22-24), 2 many (0, 5-20, 25-30, 111)."""
    last, last_two = n % 10, n % 100
    if last == 1 and last_two != 11:
        return 0
    if 2 <= last <= 4 and not 12 <= last_two <= 14:
        return 1
    return 2


def language_for(setting: str, system_locale: str) -> Language:
    """``en`` or ``ru`` as set; otherwise Russian when the system's language is Russian."""
    language = system_locale.replace("-", "_").split("_")[0].lower()
    return _SETTINGS.get(setting) or ("ru" if language == "ru" else "en")


class Translator:
    """The texts of one language."""

    def __init__(self, language: Language) -> None:
        self.language: Language = language

    def text(self, key: str, **values: object) -> str:
        return CATALOG[key][self.language].format(**values)

    def count(self, key: str, n: int, **values: object) -> str:
        forms = PLURALS[key][self.language]
        form = russian_form(n) if self.language == "ru" else (0 if n == 1 else 1)
        return forms[form].format(n=n, **values)

    def label(self, value: StrEnum) -> str:
        return LABELS[type(value)][value.value][self.language]

    def reason(self, value: StrEnum, detail: str = "") -> str:
        """A value's label, and its detail, as it is, when there is one."""
        label = self.label(value)
        return self.text("detail.reason", reason=label, detail=detail) if detail else label

    def size(self, n: int) -> str:
        """Bytes as such, larger sizes in binary multiples with one decimal, as the CLI writes
        them in English."""
        units = UNITS[self.language]
        value, index = float(n), 0
        while value >= 1024 and index < len(units) - 1:
            value /= 1024
            index += 1
        if index == 0:
            return f"{n} {units[0]}"
        return f"{value:.1f}".replace(".", DECIMAL[self.language]) + f" {units[index]}"
