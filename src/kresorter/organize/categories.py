"""Organize's categories: a fixed table, as data (decision 0012, items 21-23).

What goes where lives in ``categories.toml``; this module reads and checks it. A name is
matched by its extensions folded (``names.fold``), the longest first: ``backup.tar.gz`` is an
archive by ``tar.gz``, ``photo.JPG`` an image. A name none of whose extensions is in the table
has no category: there is no ``Other``.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

from kresorter.organize.names import fold

__all__ = [
    "Category",
    "CategoryTable",
    "Kind",
    "default_categories",
    "default_table",
    "load_categories",
]

_KEYS = ("name", "extensions")


@dataclass(frozen=True)
class Category:
    name: str  # the directory its files go to, one level below the folder
    extensions: tuple[str, ...]  # lower case, without the dot


@dataclass(frozen=True)
class Kind:
    """What the table says of a name: its category, and the extension that decided it."""

    category: str
    extension: str


class CategoryTable:
    def __init__(self, categories: Iterable[Category]) -> None:
        self._categories = tuple(categories)
        self._by_extension = {
            extension: category.name
            for category in self._categories
            for extension in category.extensions
        }

    @property
    def names(self) -> tuple[str, ...]:
        """The categories, in table order."""
        return tuple(category.name for category in self._categories)

    def match(self, name: str) -> Kind | None:
        """The kind of the file ``name``, by its longest extension in the table; ``None`` if
        none is there."""
        extensions = fold(name).split(".")[1:]
        for start in range(len(extensions)):
            extension = ".".join(extensions[start:])
            category = self._by_extension.get(extension)
            if category is not None:
                return Kind(category, extension)
        return None


def load_categories(text: str) -> tuple[Category, ...]:
    """Parse and check a table from TOML text. Raises ValueError naming what is wrong."""
    tables = tomllib.loads(text).get("category")
    if not isinstance(tables, list):
        raise ValueError("expected [[category]] tables")
    categories = tuple(_parse(index, table) for index, table in enumerate(tables, start=1))
    names: set[str] = set()
    owners: dict[str, str] = {}
    for category in categories:
        if category.name in names:
            raise ValueError(f"category {category.name!r} twice")
        names.add(category.name)
        for extension in category.extensions:
            if extension in owners:
                raise ValueError(
                    f"extension {extension!r} in two categories:"
                    f" {owners[extension]!r} and {category.name!r}"
                )
            owners[extension] = category.name
    return categories


@cache
def default_categories() -> tuple[Category, ...]:
    """The categories shipped with kresorter (``kresorter/organize/categories.toml``)."""
    data = files("kresorter.organize").joinpath("categories.toml").read_text(encoding="utf-8")
    return load_categories(data)


@cache
def default_table() -> CategoryTable:
    return CategoryTable(default_categories())


def _parse(index: int, table: Mapping[str, Any]) -> Category:
    for key in _KEYS:
        if key not in table:
            raise ValueError(f"category #{index}: missing {key!r}")
    unknown = sorted(set(table) - set(_KEYS))
    if unknown:
        raise ValueError(f"category #{index}: unknown key {unknown[0]!r}")
    name = table["name"]
    if not isinstance(name, str) or name in ("", ".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"category #{index}: {name!r} is not a directory name")
    extensions = table["extensions"]
    if not isinstance(extensions, list) or not all(isinstance(e, str) for e in extensions):
        raise ValueError(f"category {name!r}: 'extensions' must be a list of strings")
    if not extensions:
        raise ValueError(f"category {name!r}: no extensions")
    for extension in extensions:
        _check_extension(name, extension)
    return Category(name, tuple(extensions))


def _check_extension(category: str, extension: str) -> None:
    where = f"category {category!r}: extension {extension!r}"
    if "/" in extension or "\\" in extension:
        raise ValueError(f"{where} is not part of a file name")
    if "" in extension.split("."):
        raise ValueError(f"{where} must be written without its dot, and not be empty")
    if fold(extension) != extension:
        raise ValueError(f"{where} must be in lower case")
