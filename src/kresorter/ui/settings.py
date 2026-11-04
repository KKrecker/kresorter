"""The window's settings (decision 0014, items 35-36).

The window remembers only ``settings.json`` in the data directory: a JSON object with ``language``
(``system``, ``en`` or ``ru``), ``include_machine`` (a boolean), ``skipped_zones``, the names of the
safe zones left out of the scan (each a zone's last part, once; decision 0018, item 17), ``theme``
(``system``, ``light`` or ``dark``; item 1) and ``model``, the local AI's model chosen (a name
decision 0013's item 9 accepts; left out, and not written, when none is chosen; 0018 item 32).
``save`` alone writes it, after the data directory is checked (0009), through one temporary file
renamed over it, private (``0600`` on POSIX); a temporary file a crash left behind is written over.
``load`` writes nothing. A missing file means the defaults; an unreadable file, invalid JSON,
something other than an object, or a value of the wrong type or unknown means the defaults too, with
why the file was not used. A key left out takes its default; unknown keys are ignored.

The file is not a door (decision 0018, item 39): it is read with at most ``SETTINGS_BYTES`` (64
KiB) and refused beyond, as ``unreadable``; so is anything but a regular file in its place, a
directory, a link or a FIFO, on every system and before it is opened. What is put there after that
look is opened without waiting for a writer, never through a link (``O_NOFOLLOW``, POSIX) and read
up to the bound. The temporary file is written with ``O_NOFOLLOW`` too, and the rename replaces a
link in place of the file, not its target.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePath
from typing import Literal

from kresorter.core.scanner import ScanContext
from kresorter.llm.settings import is_model_name
from kresorter.storage.data_dir import PRIVATE, DataDirError, check_data_dir
from kresorter.storage.lock import PRIVATE_FILE
from kresorter.storage.session import SessionFailed, SessionFailure

__all__ = [
    "DEFAULTS",
    "LANGUAGE_SETTINGS",
    "SETTINGS_NAME",
    "TEMP_NAME",
    "THEME_SETTINGS",
    "LanguageSetting",
    "Loaded",
    "Settings",
    "ThemeSetting",
    "Unused",
    "load",
    "save",
]

SETTINGS_NAME = "settings.json"
TEMP_NAME = "settings.json.tmp"

LanguageSetting = Literal["system", "en", "ru"]
LANGUAGE_SETTINGS: tuple[LanguageSetting, ...] = ("system", "en", "ru")
_LANGUAGES: dict[str, LanguageSetting] = {setting: setting for setting in LANGUAGE_SETTINGS}
ThemeSetting = Literal["system", "light", "dark"]
THEME_SETTINGS: tuple[ThemeSetting, ...] = ("system", "light", "dark")
_THEMES: dict[str, ThemeSetting] = {setting: setting for setting in THEME_SETTINGS}
SETTINGS_BYTES = 64 * 1024  # the most read of the file; a larger one is refused
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)  # POSIX: never read or write through a link
# With O_BINARY on Windows, where os.open is otherwise in text mode: each \n would be \r\n.
_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _NO_FOLLOW
# O_NONBLOCK: a FIFO put in its place after it was looked at is opened without waiting for a writer.
_READ_FLAGS = os.O_RDONLY | _NO_FOLLOW | getattr(os, "O_NONBLOCK", 0)


@dataclass(frozen=True)
class Settings:
    language: LanguageSetting = "system"
    include_machine: bool = False
    skipped_zones: tuple[str, ...] = ()  # in the order of the zones
    theme: ThemeSetting = "system"
    model: str | None = None  # None: the local AI's default, or KRESORTER_OLLAMA_MODEL's


DEFAULTS = Settings()


class Unused(StrEnum):
    """Why the settings file was not used."""

    UNREADABLE = "unreadable"
    NOT_JSON = "not_json"
    NOT_AN_OBJECT = "not_an_object"
    WRONG_VALUE = "wrong_value"


@dataclass(frozen=True)
class Loaded:
    settings: Settings
    unused: Unused | None = None
    detail: str = ""  # the system's or the parser's words, or ``key=value`` as found


def _path(context: ScanContext) -> Path:
    return Path(context.policy.app_data_dir) / SETTINGS_NAME


def load(context: ScanContext) -> Loaded:
    """The settings, or the defaults and why the file was not used."""
    try:
        raw = _read(_path(context))
    except FileNotFoundError:
        return Loaded(DEFAULTS)
    except OSError as error:
        return Loaded(DEFAULTS, Unused.UNREADABLE, str(error))
    if raw is None:
        return Loaded(DEFAULTS, Unused.UNREADABLE, "not a regular file")
    if len(raw) > SETTINGS_BYTES:
        return Loaded(DEFAULTS, Unused.UNREADABLE, f"larger than {SETTINGS_BYTES} bytes")
    try:
        found = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as error:  # not UTF-8, not JSON, or nested too deep
        return Loaded(DEFAULTS, Unused.NOT_JSON, str(error) or type(error).__name__)
    if not isinstance(found, dict):
        return Loaded(DEFAULTS, Unused.NOT_AN_OBJECT)
    return _settings(found, tuple(PurePath(z).name for z in context.policy.default_roots()))


def _read(path: Path) -> bytes | None:
    """At most one byte more than ``SETTINGS_BYTES`` of the regular file at ``path``; ``None``
    for anything else there, looked at and never opened (Windows opens no directory)."""
    if not stat.S_ISREG(os.lstat(path).st_mode):
        return None
    with os.fdopen(os.open(path, _READ_FLAGS | getattr(os, "O_BINARY", 0)), "rb") as stream:
        return stream.read(SETTINGS_BYTES + 1)


def _zones(value: object, zones: tuple[str, ...]) -> tuple[str, ...] | None:
    """The zones named, in their order; None unless each is named once, by its name."""
    if not isinstance(value, list) or len(set(map(str, value))) != len(value):
        return None
    if not all(isinstance(name, str) and name in zones for name in value):
        return None
    return tuple(zone for zone in zones if zone in value)


def _settings(found: dict[str, object], zones: tuple[str, ...]) -> Loaded:
    language = found.get("language", DEFAULTS.language)
    chosen = _LANGUAGES.get(language) if isinstance(language, str) else None
    if chosen is None:
        return Loaded(DEFAULTS, Unused.WRONG_VALUE, f"language={json.dumps(language)}")
    include_machine = found.get("include_machine", DEFAULTS.include_machine)
    if not isinstance(include_machine, bool):
        return Loaded(
            DEFAULTS, Unused.WRONG_VALUE, f"include_machine={json.dumps(include_machine)}"
        )
    skipped = found.get("skipped_zones", [])
    skipped_zones = _zones(skipped, zones)
    if skipped_zones is None:
        return Loaded(DEFAULTS, Unused.WRONG_VALUE, f"skipped_zones={json.dumps(skipped)}")
    theme = found.get("theme", DEFAULTS.theme)
    themed = _THEMES.get(theme) if isinstance(theme, str) else None
    if themed is None:
        return Loaded(DEFAULTS, Unused.WRONG_VALUE, f"theme={json.dumps(theme)}")
    if "model" not in found:
        return Loaded(Settings(chosen, include_machine, skipped_zones, themed))
    model = found["model"]
    if not isinstance(model, str) or not is_model_name(model):
        return Loaded(DEFAULTS, Unused.WRONG_VALUE, f"model={json.dumps(model)}")
    return Loaded(Settings(chosen, include_machine, skipped_zones, themed, model))


def save(context: ScanContext, settings: Settings) -> SessionFailed | None:
    """Write the settings; ``None`` once they are, otherwise why not."""
    try:
        data_dir = check_data_dir(context.policy, context.classifier)
    except DataDirError as error:
        return SessionFailed(SessionFailure.DATA_DIR, str(error))
    content: dict[str, object] = {
        "language": settings.language,
        "include_machine": settings.include_machine,
        "skipped_zones": list(settings.skipped_zones),
        "theme": settings.theme,
    }
    if settings.model is not None:
        content["model"] = settings.model
    try:
        data_dir.mkdir(mode=PRIVATE, parents=True, exist_ok=True)
        _replace(data_dir, (json.dumps(content, indent=2) + "\n").encode("utf-8"))
    except OSError as error:
        return SessionFailed(SessionFailure.DATA_DIR_OS, str(error))
    return None


def _replace(data_dir: Path, data: bytes) -> None:
    temp = data_dir / TEMP_NAME
    fd = os.open(temp, _FLAGS | getattr(os, "O_BINARY", 0), PRIVATE_FILE)
    with os.fdopen(fd, "wb") as stream:
        temp.chmod(PRIVATE_FILE)  # a file left behind keeps its mode when it is opened
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(data_dir / SETTINGS_NAME)
