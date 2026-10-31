"""Fakes for OS boundaries. Tests never touch the live system state they describe."""

from collections.abc import Iterable
from pathlib import Path, PurePath

from safeclean.core.policy import BlockReason, PathPolicy


class FakeOpenFiles:
    """Open-file checker that reports a fixed set of paths as open."""

    reliable = True

    def __init__(self, open_paths: Iterable[PurePath] = ()) -> None:
        self._open = {str(p) for p in open_paths}
        self.calls: list[PurePath] = []

    def is_open(self, path: PurePath) -> bool:
        self.calls.append(path)
        return str(path) in self._open


class BrokenOpenFiles:
    """Open-file checker whose backend fails (e.g. access denied to the process list)."""

    reliable = True

    def is_open(self, path: PurePath) -> bool:
        raise OSError("cannot enumerate open handles")


def make_policy(tmp_path: Path, *blocked: Path, default_roots: Iterable[Path] = ()) -> PathPolicy:
    """Policy rooted in ``tmp_path``: blocks ``blocked`` (as SYSTEM), no real system paths."""
    return PathPolicy(
        flavor=type(PurePath(tmp_path)),
        case_sensitive=True,
        prefix_rules=[(p, BlockReason.SYSTEM) for p in blocked],
        root_entry_names=(),
        profile=(tmp_path / "users", tmp_path / "users" / "me", [], []),
        default_roots=list(default_roots),
    )
