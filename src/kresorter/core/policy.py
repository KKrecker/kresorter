"""Path policy: what the engine must never touch, and where it scans by default.

Two separate mechanisms (decision 0002):

* **Blacklist** (``check_path`` / ``check_file``): never a candidate, even on explicit request.
* **Default safe zones** (``default_roots``): scanned when the user selects nothing.
  Temp is deliberately absent from them but is *not* blacklisted.

What keeps a sign-in, a saved password or the open tabs is blacklisted too, wherever it is
(``sessions.toml``, decision 0020, item 13).

The policy is pure: it never touches the filesystem. Paths must already be resolved
(symlinks are handled by the walker); ``..`` is collapsed lexically.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from typing import Literal

from kresorter.core.open_files import OpenFileChecker
from kresorter.core.sessions import SessionPaths, session_patterns

Parts = tuple[str, ...]


class BlockReason(StrEnum):
    PROGRAM_FILES = "program_files"
    SYSTEM = "system"
    PROFILE = "profile"
    OPEN_FILE = "open_file"
    APP_DATA = "app_data"  # kresorter's own data dir: vault and journal (decision 0004)
    APP_PROGRAM = "app_program"  # the folders it runs from (decision 0015, item 16)
    SESSION = "session"  # a sign-in, a saved password, the open tabs (decision 0020, item 13)


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


APP_NAME = "kresorter"


def check_open(path: PurePath, open_files: OpenFileChecker) -> Verdict:
    """The open-file check of a file the blacklist allows. A failing checker counts as "open"."""
    try:
        is_open = open_files.is_open(path)
    except Exception:
        is_open = True
    return _blocked(BlockReason.OPEN_FILE) if is_open else ALLOWED


class DirectoryPolicy:
    """The blacklist of one directory's files (``PathPolicy.in_directory``): its parts
    normalized once, a name folded and added to them."""

    def __init__(
        self,
        check: Callable[[Parts], Verdict],
        parts: Parts,
        fold: Callable[[str], str],
        separators: tuple[str, ...],
    ) -> None:
        self._check, self._parts, self._fold, self._separators = check, parts, fold, separators

    def check_name(self, name: str) -> Verdict:
        """Raises ValueError for what is no name in a directory: empty, ``.``, ``..``, or with
        a separator (or a drive's colon on Windows)."""
        if name in ("", ".", "..") or any(s in name for s in self._separators):
            raise ValueError(f"not a name in a directory: {name!r}")
        return self._check((*self._parts, self._fold(name)))


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
        program_dirs: Sequence[PurePath] = (),
        sessions: Iterable[str] = (),
    ) -> None:
        self._flavor = flavor
        self._case_sensitive = case_sensitive
        self._app_data_dir = app_data_dir
        # APP_DATA first: the vault is blocked even inside a default root or a system path;
        # then the folders kresorter runs from, which say so inside a system path too.
        rules = [
            (app_data_dir, BlockReason.APP_DATA),
            *((d, BlockReason.APP_PROGRAM) for d in program_dirs),
            *prefix_rules,
        ]
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
        self._sessions = SessionPaths(sessions, self._fold)

    # --- construction ------------------------------------------------------------------------

    @classmethod
    def for_windows(
        cls, env: Mapping[str, str], *, program_dirs: Sequence[PurePath] = ()
    ) -> PathPolicy:
        """Build a Windows policy. Environment values are added to defaults, never replace them.
        ``program_dirs``: the folders kresorter runs from, blocked like its data."""
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
            program_dirs=program_dirs,
            sessions=session_patterns(),
        )

    @classmethod
    def for_posix(
        cls,
        *,
        home: PurePosixPath,
        platform: Literal["linux", "darwin"],
        env: Mapping[str, str] | None = None,
        program_dirs: Sequence[PurePath] = (),
    ) -> PathPolicy:
        """Build a Linux or macOS policy. macOS paths are compared case-insensitively (APFS).
        ``program_dirs``: the folders kresorter runs from, blocked like its data."""
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
            program_dirs=program_dirs,
            sessions=session_patterns(),
        )

    # --- public API ----------------------------------------------------------------------------

    def check_path(self, path: PurePath) -> Verdict:
        """Blacklist check only. Raises ValueError for non-absolute paths."""
        return self._check_parts(self._normalize(path))

    def in_directory(self, directory: PurePath) -> DirectoryPolicy:
        """The blacklist for the files of ``directory``, checked by their names alone with the
        answer ``check_path`` gives on their paths (decision 0018, item 14). Raises ValueError
        for a non-absolute directory."""
        separators = ("\\", "/", ":") if self._flavor is PureWindowsPath else ("/",)
        parts = self._normalize(directory)
        held = self._sessions.holds(parts[1:])
        is_session = self._sessions.names_in(parts[1:])

        def check(named: Parts) -> Verdict:
            verdict = self._check_unsessioned(named)
            if verdict.allowed and (held or is_session(named[-1])):
                return _blocked(BlockReason.SESSION)
            return verdict

        return DirectoryPolicy(check, parts, self._fold, separators)

    def check_file(self, path: PurePath, open_files: OpenFileChecker) -> Verdict:
        """Blacklist check, then open-file check. A failing checker counts as "open"."""
        verdict = self.check_path(path)
        return check_open(path, open_files) if verdict.allowed else verdict

    def _check_parts(self, parts: Parts) -> Verdict:
        verdict = self._check_unsessioned(parts)
        if verdict.allowed and self._sessions.holds(parts[1:]):
            return _blocked(BlockReason.SESSION)
        return verdict

    def _check_unsessioned(self, parts: Parts) -> Verdict:
        """Every rule but the sessions', which come last."""
        for prefix, reason in self._prefix_rules:
            if _is_under(parts, prefix):
                return _blocked(reason)
        if len(parts) >= 2 and parts[1] in self._root_entry_names:
            return _blocked(BlockReason.SYSTEM)
        return _blocked(BlockReason.PROFILE) if self._is_protected_profile(parts) else ALLOWED

    def holds_home(self, path: PurePath) -> bool:
        """True for the user's home directory and every directory above it: their top level
        holds what other programs expect (decision 0012, item 7). Raises ValueError for a
        non-absolute path."""
        return _is_under(self._profile.own_home, self._normalize(path))

    @property
    def app_data_dir(self) -> PurePath:
        """kresorter's own data directory (vault, journal). Always blocked as APP_DATA."""
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
