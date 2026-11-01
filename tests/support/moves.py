"""Organize's moves in tests: renames that fail where a test wants, crashes that are real exits
(of a batch at a rename), and where the journal says each file is (decision 0012, items 27
and 40).

Every file a test sorts holds its own name, so what a path holds tells which file is there.
``files`` is every regular file under a folder, foreign ones included: an overwrite or a
deletion shows as a changed or missing entry. ``tree`` adds directories and links.
"""

from __future__ import annotations

import errno
import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal

from support.files import write

Fault = Literal["before", "after", "interrupt", "exit-before", "exit-after"]
Moves = Sequence[tuple[Path, Path]]

CRASHED = 70  # the exit status of a child that crashed where it was told to
A, B, C = "a.jpg", "b.pdf", "c.mp3"
SOURCES = {A: A, B: B, C: C}
MOVED = {A: f"Images/{A}", B: f"Documents/{B}", C: f"Audio/{C}"}


class Interrupt(BaseException):
    """Stands for ``KeyboardInterrupt``: not an ``OSError``, and the process lives on."""


class FlakyRename:
    """``os.rename``, except for the paths in ``faults``, by the path being renamed:

    - ``before`` raises ``OSError`` without moving, ``after`` moves and then raises it;
    - ``interrupt`` raises ``Interrupt`` without moving;
    - ``exit-before`` and ``exit-after`` end the process (``os._exit``) before or after the
      move: a crash, and nothing after it runs.

    ``meanwhile`` runs right before the rename of its path: another program at work.
    """

    def __init__(
        self,
        faults: Mapping[Path, Fault] | None = None,
        meanwhile: Mapping[Path, Callable[[], object]] | None = None,
    ) -> None:
        self._faults = dict(faults or {})
        self._meanwhile = dict(meanwhile or {})
        self.calls: list[tuple[Path, Path]] = []

    def __call__(self, source: Path, destination: Path) -> None:
        self.calls.append((source, destination))
        if source in self._meanwhile:
            self._meanwhile[source]()
        fault = self._faults.get(source)
        if fault == "before":
            raise OSError(errno.EACCES, "refused before the move", str(source))
        if fault == "interrupt":
            raise Interrupt
        if fault == "exit-before":
            os._exit(CRASHED)
        source.rename(destination)
        if fault == "after":
            raise OSError(errno.EIO, "failed after the move", str(source))
        if fault == "exit-after":
            os._exit(CRASHED)


def three_files(zone: Path) -> Path:
    """``zone/Downloads`` with a photo, a document and a song, each holding its own name."""
    folder = zone / "Downloads"
    for name in (A, B, C):
        write(folder / name, name.encode())
    return folder


def planned(folder: Path) -> list[tuple[Path, Path]]:
    """The three moves of ``three_files``: a, b, then c."""
    return [(folder / name, folder / MOVED[name]) for name in (A, B, C)]


def crash(journal: Path, folder: Path, moves: Moves, faults: Mapping[Path, Fault]) -> None:
    """Carry the batch out in a child process that crashes at its first ``exit-*`` fault."""
    spec = {
        "journal": str(journal),
        "folder": str(folder),
        "moves": [[str(source), str(destination)] for source, destination in moves],
        "faults": {str(path): fault for path, fault in faults.items()},
    }
    child = _child(_CARRY_OUT, spec)
    assert child.returncode == CRASHED, child.stderr


def _child(code: str, spec: object) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    return subprocess.run(
        [sys.executable, "-c", code, json.dumps(spec)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


_CARRY_OUT = """
import json, sys
from pathlib import Path
from safeclean.organize.mover import carry_out
from safeclean.storage.db import connect
from support.moves import FlakyRename
spec = json.loads(sys.argv[1])
faults = {Path(path): fault for path, fault in spec["faults"].items()}
moves = [(Path(source), Path(destination)) for source, destination in spec["moves"]]
carry_out(connect(Path(spec["journal"])), Path(spec["folder"]), moves, rename=FlakyRename(faults))
"""


def where(conn: sqlite3.Connection, folder: Path) -> dict[str, str]:
    """Where the journal says each file is, by name: the path its move's state points at,
    relative to ``folder`` (``done`` the destination, ``rolled_back`` the source), or the state
    itself when it points at neither (``pending``, ``failed``)."""
    said: dict[str, str] = {}
    for source, destination, state in conn.execute(
        "SELECT source, destination, state FROM moves ORDER BY id"
    ):
        path = {"done": destination, "rolled_back": source}.get(state)
        said[Path(source).name] = (
            state if path is None else Path(path).relative_to(folder).as_posix()
        )
    return said


def content(located: Mapping[str, str]) -> dict[str, bytes]:
    """What ``files`` holds when every file is where ``located`` says and nothing else is."""
    return {path: name.encode() for name, path in located.items()}


def files(folder: Path) -> dict[str, bytes]:
    """Every regular file under ``folder``, by its relative path, with what it holds."""
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and not p.is_symlink()
    }


def tree(root: Path) -> dict[str, bytes | str]:
    """``files`` with directories (``"dir"``) and links (``"-> target"``) too."""
    found: dict[str, bytes | str] = {}
    for p in sorted(root.rglob("*")):
        name = p.relative_to(root).as_posix()
        if p.is_symlink():
            found[name] = f"-> {p.readlink()}"
        elif p.is_dir():
            found[name] = "dir"
        else:
            found[name] = p.read_bytes()
    return found


def batches(conn: sqlite3.Connection) -> list[str]:
    """The state of every batch, oldest first."""
    return [state for (state,) in conn.execute("SELECT state FROM move_batches ORDER BY id")]
