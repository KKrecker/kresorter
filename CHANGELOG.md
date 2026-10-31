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
- `quarantine.vault` and `quarantine.service`: private vault (0700) in the data directory, journal-before-move, same-device `Path.replace` only (`CROSS_DEVICE` refused), atomic batch with rollback that never overwrites, `recover()` that trusts only an exact vault copy (decision 0006). Default data directories stay blocked under custom `XDG_DATA_HOME`/`LOCALAPPDATA`.
- Restore: `QuarantineService.restore()` puts files back with journaled mode/atime/mtime, never overwrites (`CONFLICT`), recreates missing parents, refuses a swapped parent chain, marks a missing or changed vault copy `lost`; items are independent; interrupted restores are reconciled by `recover()` (decision 0007). Journal schema v2: `items.atime_ns`. Duplicate candidates in one batch are refused up front.
- Purge: `QuarantineService.plan_purge()` (read-only plan with `total_bytes` and a one-time token) and `purge(plan)` (same service, unchanged plan, once); deletes only vault copies that still match the journal, never the original path; a changed copy becomes `lost` and is kept; `DELETE_FAILED` keeps the item quarantined; interrupted purges are reconciled by `recover()` (`RecoveryReport.purged`). `quarantine.purge.delete_from_vault` is the single deletion point (vault slots only, `UnsafeDeleteError`); the AST guard now also catches uncalled references and `from os import remove`-style imports, with a pinned one-file allowlist (decision 0008).
- `safeclean quarantine add / list / restore / purge [--yes]`: purge shows its plan and deletes only with `--yes`; every command recovers interrupted operations first (LOST warnings on stderr); exit codes 0/1/2/3 (3 = unsafe to run); the data directory is checked before anything is created and kept 0700 (decision 0009). `safeclean.text` holds the shared size formatting.
- `storage.lock.InstanceLock`: single-instance lock on the data directory (`flock` / `msvcrt.locking`, released by the kernel on crash, lock file 0600 and never deleted); a second `safeclean quarantine` on the same data directory exits with 3 (decision 0009, addendum).
- `safeclean scan` (and `python -m safeclean`): text/JSON report of junk candidates, duplicate groups and skips; read-only.

### Fixed
- An unopenable journal (`sqlite3.Error`) exits with 3 and a message instead of a traceback.
- Quarantine rollback no longer loses track of a file whose rename completed just before an interrupt: rollback checks the vault slot on disk; `recover()` also reconciles quarantined items of an interrupted rollback (decision 0006, addendum).

### Changed
- `safeclean scan` uses the real open-file check on Linux (`checker_for_platform()`); other OSes still disclose that it is missing.
- Temp is no longer a default safe zone; scanned only on explicit choice (decision 0002).
