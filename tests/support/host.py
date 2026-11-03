"""What a test needs of the system it runs on: CI runs the tests on Linux and on Windows
(decision 0015, item 20).

On Windows ``os.open`` opens a file in text mode unless ``os.O_BINARY`` is given: each ``\\n``
written becomes ``\\r\\n``. ``record_opens`` shows the flags a file is opened with on every
system: where ``os.O_BINARY`` is missing, a bit no system uses stands for it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest

UNUSED_BIT = 1 << 30  # stands for os.O_BINARY where there is none


@dataclass
class Opens:
    binary: int  # os.O_BINARY, or the bit that stands for it
    flags: dict[str, int] = field(default_factory=dict)  # by the file's name, the last open

    def in_binary(self, name: str) -> bool:
        return bool(self.flags[name] & self.binary)


def record_opens(monkeypatch: pytest.MonkeyPatch) -> Opens:
    """Every ``os.open`` from now on, its flags recorded; the bit that stands for
    ``os.O_BINARY`` is taken out before the real call."""
    real = os.open
    stand_in = 0 if hasattr(os, "O_BINARY") else UNUSED_BIT
    if stand_in:
        monkeypatch.setattr(os, "O_BINARY", stand_in, raising=False)
    opens = Opens(binary=getattr(os, "O_BINARY", stand_in))

    def recording(path: str | Path, flags: int, mode: int = 0o777) -> int:
        opens.flags[Path(path).name] = flags
        return real(path, flags & ~stand_in, mode)

    monkeypatch.setattr(os, "open", recording)
    return opens
