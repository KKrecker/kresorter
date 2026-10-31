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
- `safeclean scan` (and `python -m safeclean`): text/JSON report of junk candidates, duplicate groups and skips; read-only.

### Changed
- Temp is no longer a default safe zone; scanned only on explicit choice (decision 0002).
