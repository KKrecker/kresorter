"""What a test needs of the system it runs on: CI runs the tests on Linux and on Windows
(decision 0015, item 20).

Windows keeps no permission bits: a file shows 0o666, or 0o444 when it is read-only, a
directory 0o777 (0o555); ``as_kept`` is what a mode shows there. It has no FIFOs, keeps times in
steps of 100 ns, and takes a name in another case for the same name. A path is written with
``\\``: ``native`` is a relative path as the system writes it. A test that needs what Windows
has not is ``posix_only``, with the reason.

On Windows ``os.open`` opens a file in text mode unless ``os.O_BINARY`` is given: each ``\\n``
written becomes ``\\r\\n``. ``record_opens`` shows the flags a file is opened with on every
system: where ``os.O_BINARY`` is missing, a bit no system uses stands for it.

The junk rules read a path as their system writes it: ``host_classifier`` is the system's own,
Windows' rules on Windows and Linux's elsewhere, for the paths under ``tmp_path``. Its
temporary folder is junk to one rule, ``posix-temp`` (``/tmp``) on Linux and
``windows-user-temp`` (``AppData\\Local\\Temp``) on Windows: ``host_rules`` are the default rules
without it, so that a test's tree is junk only where the test makes it so.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePath

import pytest

from kresorter.core.heuristics import JunkClassifier, JunkRule, default_rules

WINDOWS = sys.platform == "win32"
MTIME_STEP_NS = 100 if WINDOWS else 1  # the smallest change of a time the system keeps
UNUSED_BIT = 1 << 30  # stands for os.O_BINARY where there is none


TEMP_RULE = "windows-user-temp" if WINDOWS else "posix-temp"  # tmp_path is junk to it


def host_rules() -> list[JunkRule]:
    """Every default rule but ``TEMP_RULE``."""
    return [rule for rule in default_rules() if rule.id != TEMP_RULE]


def host_classifier(rules: Iterable[JunkRule]) -> JunkClassifier:
    """``rules`` on the running system's paths: Windows' on Windows, Linux's elsewhere."""
    return JunkClassifier(rules, platform="windows" if WINDOWS else "linux")


def posix_only(reason: str) -> pytest.MarkDecorator:
    """Skipped on Windows, which has not what ``reason`` says."""
    return pytest.mark.skipif(WINDOWS, reason=reason)


def as_kept(bits: int, *, directory: bool = False) -> int:
    """The permission bits a file or directory given ``bits`` shows: those on POSIX; on
    Windows only whether the owner may write it."""
    if not WINDOWS:
        return bits
    readable = 0o555 if directory else 0o444
    return readable | (0o222 if bits & stat.S_IWUSR else 0)


def native(relative: str) -> str:
    """``relative``, written with ``/``, as the system writes it: on Windows with ``\\``."""
    return str(PurePath(relative))


def cannot_list(file: Path) -> str:
    """What the system says of listing ``file``, a file: ``Not a directory`` on POSIX, ``The
    directory name is invalid`` on Windows."""
    with pytest.raises(NotADirectoryError) as listed:
        list(file.iterdir())
    return str(listed.value.strerror)


def make_fifo(path: Path) -> None:
    """A FIFO at ``path``; the test is skipped on Windows, which has none."""
    mkfifo = getattr(os, "mkfifo", None)
    if mkfifo is None:
        pytest.skip("Windows has no FIFOs")
    mkfifo(path)


def alias(link: Path, target: Path) -> None:
    """``link`` stands for the directory ``target``: a link to it, unless the two are one name
    on this system (on Windows, the same name in another case)."""
    if not (WINDOWS and link.name.casefold() == target.name.casefold()):
        link.symlink_to(target, target_is_directory=True)


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
