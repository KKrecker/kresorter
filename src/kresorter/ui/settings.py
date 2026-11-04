"""The window's settings (decision 0014, items 35-36).

The window remembers only ``settings.json`` in the data directory: a JSON object with
``language`` (``system``, ``en`` or ``ru``), ``include_machine`` (a boolean) and
``skipped_zones``, the names of the safe zones left out of the scan (each a zone's last part,
once; decision 0018, item 17). ``save`` alone
writes it, after the data directory is checked (0009), through one temporary file renamed over
it, private (``0600`` on POSIX); a temporary file a crash left behind is written over. ``load``
writes nothing. A missing file means the defaults; an unreadable file, invalid JSON, something
other than an object, or a value of the wrong type or unknown means the defaults too, with why
the file was not used. A key left out takes its default; unknown keys are ignored.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePath
from typing import Literal

from kresorter.core.scanner import ScanContext
from kresorter.storage.data_dir import PRIVATE, DataDirError, check_data_dir
from kresorter.storage.lock import PRIVATE_FILE
from kresorter.storage.session import SessionFailed, SessionFailure

__all__ = [
    "DEFAULTS",
    "LANGUAGE_SETTINGS",
    "SETTINGS_NAME",
    "TEMP_NAME",
    "LanguageSetting",
    "Loaded",
    "Settings",
    "Unused",
    "load",
    "save",
]

SETTINGS_NAME = "settings.json"
TEMP_NAME = "settings.json.tmp"

LanguageSetting = Literal["system", "en", "ru"]
LANGUAGE_SETTINGS: tuple[LanguageSetting, ...] = ("system", "en", "ru")
_LANGUAGES: dict[str, LanguageSetting] = {setting: setting for setting in LANGUAGE_SETTINGS}
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)  # POSIX: never write through a link
# With O_BINARY on Windows, where os.open is otherwise in text mode: each \n would be \r\n.
_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _NO_FOLLOW


@dataclass(frozen=True)
class Settings:
    language: LanguageSetting = "system"
    include_machine: bool = False
    skipped_zones: tuple[str, ...] = ()  # in the order of the zones


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
        raw = _path(context).read_bytes()
    except FileNotFoundError:
        return Loaded(DEFAULTS)
    except OSError as error:
        return Loaded(DEFAULTS, Unused.UNREADABLE, str(error))
    try:
        found = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as error:  # not UTF-8, not JSON, or nested too deep
        return Loaded(DEFAULTS, Unused.NOT_JSON, str(error) or type(error).__name__)
    if not isinstance(found, dict):
        return Loaded(DEFAULTS, Unused.NOT_AN_OBJECT)
    return _settings(found, tuple(PurePath(z).name for z in context.policy.default_roots()))


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
    return Loaded(Settings(chosen, include_machine, skipped_zones))


def save(context: ScanContext, settings: Settings) -> SessionFailed | None:
    """Write the settings; ``None`` once they are, otherwise why not."""
    try:
        data_dir = check_data_dir(context.policy, context.classifier)
    except DataDirError as error:
        return SessionFailed(SessionFailure.DATA_DIR, str(error))
    content = {
        "language": settings.language,
        "include_machine": settings.include_machine,
        "skipped_zones": list(settings.skipped_zones),
    }
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
