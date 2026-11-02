"""What keeps the window's tests off the running system (decision 0014, item 39).

``guard`` refuses the contexts of the running system (``safeclean.environment`` builds them only
through ``default_context`` and ``default_autostart_context``), points home and the data and
settings folders at an empty temporary home, and gives the local AI an address that is refused
before any connection. The network guard of 0013 item 29 applies to every test already.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from safeclean import environment

REFUSED_URL = "http://192.0.2.1:11434"  # not loopback: refused as a setting, never connected
HOME_VARIABLES = (
    "HOME",
    "USERPROFILE",
    "XDG_DATA_HOME",
    "XDG_CONFIG_HOME",
    "LOCALAPPDATA",
    "APPDATA",
)


class LiveSystemError(AssertionError):
    """A window test reached for the running system."""


def _refused(*_: object) -> NoReturn:
    raise LiveSystemError("a window test reached for the running system")


def guard(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setattr(environment, "default_context", _refused)
    monkeypatch.setattr(environment, "default_autostart_context", _refused)
    places = {
        "HOME": home,
        "USERPROFILE": home,
        "XDG_DATA_HOME": home / ".local" / "share",
        "XDG_CONFIG_HOME": home / ".config",
        "LOCALAPPDATA": home / "AppData" / "Local",
        "APPDATA": home / "AppData" / "Roaming",
    }
    for name in HOME_VARIABLES:
        monkeypatch.setenv(name, str(places[name]))
    monkeypatch.setenv("SAFECLEAN_OLLAMA_URL", REFUSED_URL)
