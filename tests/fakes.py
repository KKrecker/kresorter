"""Fakes for OS boundaries. Tests never touch the live system state they describe."""

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePath

from safeclean.autostart.registry import Hive, RegistryError, RegValue
from safeclean.core.policy import BlockReason, PathPolicy

RegistryKeys = Mapping[tuple[Hive, str], Sequence[RegValue]]


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


def make_policy(
    tmp_path: Path,
    *blocked: Path,
    default_roots: Iterable[Path] = (),
    app_data_dir: Path | None = None,
) -> PathPolicy:
    """Policy rooted in ``tmp_path``: blocks ``blocked`` (as SYSTEM), no real system paths.

    The app data directory defaults to ``tmp_path / "appdata"`` (blocked as APP_DATA).
    """
    return PathPolicy(
        flavor=type(PurePath(tmp_path)),
        case_sensitive=True,
        prefix_rules=[(p, BlockReason.SYSTEM) for p in blocked],
        root_entry_names=(),
        profile=(tmp_path / "users", tmp_path / "users" / "me", [], []),
        default_roots=list(default_roots),
        app_data_dir=app_data_dir or tmp_path / "appdata",
    )


class FakeRegistry:
    """Read-only registry: keys by (hive, path); a denied key raises like a real one would."""

    def __init__(self, keys: RegistryKeys, denied: Iterable[tuple[Hive, str]] = ()) -> None:
        self._keys = dict(keys)
        self._denied = set(denied)
        self.reads: list[tuple[Hive, str]] = []

    def values(self, hive: Hive, key: str) -> Sequence[RegValue] | None:
        self.reads.append((hive, key))
        if (hive, key) in self._denied:
            raise RegistryError("access denied")
        return self._keys.get((hive, key))
