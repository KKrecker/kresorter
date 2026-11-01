"""Path policy: what the engine must never touch, and where it scans by default.

Two separate mechanisms (decision 0002):

* **Blacklist** (``check_path`` / ``check_file``): never a candidate, even on explicit request.
* **Default safe zones** (``default_roots``): scanned when the user selects nothing.
  Temp is deliberately absent from them but is *not* blacklisted.

The policy is pure: it never touches the filesystem. Paths must already be resolved
(symlinks are handled by the walker); ``..`` is collapsed lexically.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from typing import Literal

from safeclean.core.open_files import OpenFileChecker

Parts = tuple[str, ...]


class BlockReason(StrEnum):
    PROGRAM_FILES = "program_files"
    SYSTEM = "system"
    PROFILE = "profile"
    OPEN_FILE = "open_file"
    APP_DATA = "app_data"  # safeclean's own data dir: vault and journal (decision 0004)


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: BlockReason | None


ALLOWED = Verdict(allowed=True, reason=None)


def _blocked(reason: BlockReason) -> Verdict:
    return Verdict(allowed=False, reason=reason)


@dataclass(frozen=True)
class _ProfileRules:
    users_root: Parts
    own_home: Parts
    blocked_subpaths: tuple[Parts, ...]
    blocked_name_prefixes: tuple[str, ...]


APP_NAME = "safeclean"


def _xdg_data_home(default: PurePosixPath, env: Mapping[str, str]) -> PurePosixPath:
    """``$XDG_DATA_HOME`` if absolute (the spec says to ignore relative values), else default."""
    value = PurePosixPath(env.get("XDG_DATA_HOME") or ".")
    return value if value.is_absolute() else default


def _is_under(parts: Parts, prefix: Parts) -> bool:
    return parts[: len(prefix)] == prefix


class PathPolicy:
    def __init__(
        self,
        *,
        flavor: type[PurePath],
        case_sensitive: bool,
        prefix_rules: Sequence[tuple[PurePath, BlockReason]],
        root_entry_names: Iterable[str],
        profile: tuple[PurePath, PurePath, Sequence[PurePath], Sequence[str]],
        default_roots: Sequence[PurePath],
        app_data_dir: PurePath,
    ) -> None:
        self._flavor = flavor
        self._case_sensitive = case_sensitive
        self._app_data_dir = app_data_dir
        # APP_DATA first: the vault is blocked even inside a default root or a system path.
        rules = [(app_data_dir, BlockReason.APP_DATA), *prefix_rules]
        self._prefix_rules = tuple((self._normalize(p), r) for p, r in rules)
        self._root_entry_names = frozenset(self._fold(n) for n in root_entry_names)
        users_root, home, subpaths, name_prefixes = profile
        home_parts = self._normalize(home)
        self._profile = _ProfileRules(
            users_root=self._normalize(users_root),
            own_home=home_parts,
            blocked_subpaths=tuple(home_parts + self._relative(s) for s in subpaths),
            blocked_name_prefixes=tuple(self._fold(n) for n in name_prefixes),
        )
        self._default_roots = tuple(default_roots)

    # --- construction ------------------------------------------------------------------------

    @classmethod
    def for_windows(cls, env: Mapping[str, str]) -> PathPolicy:
        """Build a Windows policy. Environment values are added to defaults, never replace them."""
        drive = env.get("SystemDrive", "C:")
        root = PureWindowsPath(drive + "\\")
        home = PureWindowsPath(env.get("USERPROFILE", str(root / "Users" / "Default")))

        def paths(keys: Iterable[str], defaults: Iterable[str]) -> list[PureWindowsPath]:
            from_env = [PureWindowsPath(env[k]) for k in keys if env.get(k)]
            return from_env + [root / d for d in defaults]

        program_files = paths(
            ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"),
            ("Program Files", "Program Files (x86)"),
        )
        system = paths(("SystemRoot", "ProgramData"), ("Windows", "ProgramData"))
        default_local = home / "AppData" / "Local"
        local = env.get("LOCALAPPDATA")
        local_root = PureWindowsPath(local) if local else default_local
        return cls(
            flavor=PureWindowsPath,
            case_sensitive=False,
            # The default data dir stays blocked when LOCALAPPDATA points elsewhere.
            prefix_rules=[(default_local / APP_NAME, BlockReason.APP_DATA)]
            + [(p, BlockReason.PROGRAM_FILES) for p in program_files]
            + [(p, BlockReason.SYSTEM) for p in system],
            root_entry_names=(
                "pagefile.sys",
                "hiberfil.sys",
                "swapfile.sys",
                "$Recycle.Bin",
                "System Volume Information",
            ),
            profile=(
                home.parent,
                home,
                [PureWindowsPath(r"AppData\Roaming")],
                ["ntuser.dat", "usrclass.dat"],
            ),
            default_roots=[home / ".cache", home / "Downloads"],
            app_data_dir=local_root / APP_NAME,
        )

    @classmethod
    def for_posix(
        cls,
        *,
        home: PurePosixPath,
        platform: Literal["linux", "darwin"],
        env: Mapping[str, str] | None = None,
    ) -> PathPolicy:
        """Build a Linux or macOS policy. macOS paths are compared case-insensitively (APFS)."""
        system: tuple[str, ...]
        program_files: tuple[str, ...]
        common = ("/bin", "/sbin", "/usr", "/etc", "/dev", "/var/lib", "/var/db")
        if platform == "darwin":
            system = (*common, "/System", "/Library", "/private", "/cores")
            program_files = ("/Applications", "/opt")
            default_data_root = home / "Library" / "Application Support"
            data_root = default_data_root
        else:
            system = (*common, "/boot", "/lib", "/lib32", "/lib64", "/proc", "/sys", "/run")
            program_files = ("/opt", "/snap")
            default_data_root = home / ".local" / "share"
            data_root = _xdg_data_home(default_data_root, env or {})
        return cls(
            flavor=PurePosixPath,
            case_sensitive=platform == "linux",
            # The default data dir stays blocked when XDG_DATA_HOME points elsewhere.
            prefix_rules=[(default_data_root / APP_NAME, BlockReason.APP_DATA)]
            + [(PurePosixPath(p), BlockReason.SYSTEM) for p in system]
            + [(PurePosixPath(p), BlockReason.PROGRAM_FILES) for p in program_files],
            root_entry_names=(),
            profile=(home.parent, home, [PurePosixPath(".ssh"), PurePosixPath(".gnupg")], []),
            default_roots=[home / ".cache", home / "Downloads"],
            app_data_dir=data_root / APP_NAME,
        )

    # --- public API ----------------------------------------------------------------------------

    def check_path(self, path: PurePath) -> Verdict:
        """Blacklist check only. Raises ValueError for non-absolute paths."""
        parts = self._normalize(path)
        for prefix, reason in self._prefix_rules:
            if _is_under(parts, prefix):
                return _blocked(reason)
        if len(parts) >= 2 and parts[1] in self._root_entry_names:
            return _blocked(BlockReason.SYSTEM)
        return _blocked(BlockReason.PROFILE) if self._is_protected_profile(parts) else ALLOWED

    def check_file(self, path: PurePath, open_files: OpenFileChecker) -> Verdict:
        """Blacklist check, then open-file check. A failing checker counts as "open"."""
        verdict = self.check_path(path)
        if not verdict.allowed:
            return verdict
        try:
            is_open = open_files.is_open(path)
        except Exception:
            is_open = True
        return _blocked(BlockReason.OPEN_FILE) if is_open else ALLOWED

    def holds_home(self, path: PurePath) -> bool:
        """True for the user's home directory and every directory above it: their top level
        holds what other programs expect (decision 0012, item 7). Raises ValueError for a
        non-absolute path."""
        return _is_under(self._profile.own_home, self._normalize(path))

    @property
    def app_data_dir(self) -> PurePath:
        """safeclean's own data directory (vault, journal). Always blocked as APP_DATA."""
        return self._app_data_dir

    def default_roots(self) -> tuple[PurePath, ...]:
        """Safe zones scanned when the user selects nothing. Temp is never among them."""
        return self._default_roots

    # --- helpers -------------------------------------------------------------------------------

    def _is_protected_profile(self, parts: Parts) -> bool:
        rules = self._profile
        if not _is_under(parts, rules.users_root) or parts == rules.users_root:
            return False
        if not _is_under(parts, rules.own_home):
            return True
        if any(_is_under(parts, sub) for sub in rules.blocked_subpaths):
            return True
        return parts[-1].startswith(rules.blocked_name_prefixes)

    def _fold(self, text: str) -> str:
        return text if self._case_sensitive else text.casefold()

    def _relative(self, path: PurePath) -> Parts:
        return tuple(self._fold(p) for p in self._flavor(path).parts)

    def _normalize(self, path: PurePath) -> Parts:
        pure = self._flavor(path)
        if not pure.is_absolute():
            raise ValueError(f"path must be absolute: {path}")
        anchor, *rest = pure.parts
        stack: list[str] = []
        for part in rest:
            if part == "..":
                if stack:
                    stack.pop()
            else:  # PurePath already drops "." components
                stack.append(self._fold(part))
        return (self._fold(anchor), *stack)
