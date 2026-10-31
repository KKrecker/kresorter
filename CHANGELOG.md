# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Project skeleton, tooling (ruff, mypy strict, pytest + coverage ≥ 80%), Linux CI.
- Guard against direct file deletion in code and tests.
- `core.policy`: path blacklist (Windows/Linux/macOS) and default safe zones (`~/.cache`, `~/Downloads`).
- `core.walker`: safe traversal (no symlinks/junctions, pruning of blocked dirs, every skip reported).

### Changed
- Temp is no longer a default safe zone; scanned only on explicit choice (decision 0002).
