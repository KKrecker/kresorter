"""Fakes for OS boundaries. Tests never touch the live system state they describe."""

from collections.abc import Iterable
from pathlib import PurePath


class FakeOpenFiles:
    """Open-file checker that reports a fixed set of paths as open."""

    def __init__(self, open_paths: Iterable[PurePath] = ()) -> None:
        self._open = {str(p) for p in open_paths}
        self.calls: list[PurePath] = []

    def is_open(self, path: PurePath) -> bool:
        self.calls.append(path)
        return str(path) in self._open


class BrokenOpenFiles:
    """Open-file checker whose backend fails (e.g. access denied to the process list)."""

    def is_open(self, path: PurePath) -> bool:
        raise OSError("cannot enumerate open handles")
