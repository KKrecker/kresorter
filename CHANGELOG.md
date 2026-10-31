# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Project skeleton, tooling (ruff, mypy strict, pytest + coverage ≥ 80%), Linux CI.
- Guard against direct file deletion in code and tests.
- `core.policy`: path blacklist (Windows/Linux/macOS) and default safe zones (`~/.cache`, `~/Downloads`).
- `core.walker`: safe traversal (no symlinks/junctions, pruning of blocked dirs, every skip reported).
- `core.hashing`: streaming BLAKE2b; duplicate candidates via size groups -> prefix hash -> full hash; files changed since scan or during hashing reported as `changed`.
- `core.heuristics` + `core/junk_rules.toml`: junk rules as data (14 default rules: caches, temp, thumbnails, crash dumps, OS metadata) with strict validation.
- `FileEntry.mtime_ns` (int) replaces float `mtime`: exact change detection.
- `storage`: SQLite journal (WAL, foreign keys, synchronous=FULL, busy_timeout), all-or-nothing versioned migrations, `BEGIN IMMEDIATE` transactions with rollback on any exception; schema v1 (`operations`, `items`, STRICT + CHECK).
- `core.open_files` package: `reliable` flag on the checker protocol; Linux backend `ProcFdChecker` (`/proc/*/fd`, matches by `st_dev`/`st_ino`, fails closed); `checker_for_platform()` gives other OSes an unreliable placeholder (decision 0005).
- `BlockReason.APP_DATA`: safeclean's data directory (`$XDG_DATA_HOME/safeclean` or `~/.local/share/safeclean`, `~/Library/Application Support/safeclean`, `%LOCALAPPDATA%\safeclean`) is blacklisted, so the vault and journal never appear in a scan, even when a parent is scanned explicitly; exposed as `PathPolicy.app_data_dir` (decision 0004).
- `quarantine.preflight`: per-item re-validation right before acting (policy -> disk -> duplicate twin -> open files last); 11 refusal reasons incl. parent swapped for a link and hard-linked twin; refuses an unreliable open-file checker.
- `safeclean scan` (and `python -m safeclean`): text/JSON report of junk candidates, duplicate groups and skips; read-only.

### Changed
- Temp is no longer a default safe zone; scanned only on explicit choice (decision 0002).
