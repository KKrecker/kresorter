# 0002. Registry as opt-in setting, Temp out of default safe zones, file organizer module

- Status: accepted
- Date: 2026-10-31
- Amends: 0001 (decision 3)

## 1. Registry access is an optional setting, not absent

**Decision.** Registry access becomes an opt-in setting in the UI (off by default). It is **not**
implemented in the MVP; it arrives in a late iteration together with the autostart module.
Scope stays as in 0001: Run/RunOnce keys only, every change logged and reversible, tests only on
a fake hive.

**Consequences.** Step 1 is unaffected: the engine has no registry code and no dependency on it.

## 2. Temp is removed from the default safe zones

**Context.** Temporary files come back on their own, so cleaning them brings little lasting value.
Temp directories also hold live data (browser cookies, sessions, lock files of running programs).
The risk of hitting something alive outweighs the benefit.

**Decision.**

- Default scan roots (used when the user selects nothing) are only `<home>/.cache` and
  `<home>/Downloads`, on every platform.
- Temp (`/tmp`, `/var/tmp`, `%TEMP%`, `AppData\Local\Temp`) is scanned **only if the user selects
  it explicitly**.
- Temp is **not** blacklisted. The blacklist means "never touch, even on explicit request"; Temp
  means "not by default". These are two separate mechanisms in `PathPolicy`:
  `check_path()` / `check_file()` (blacklist) and `default_roots()` (safe zones).

## 3. New module: file organizer

**Feature.** The app analyzes a user-selected folder and proposes a structure for sorting files
into categories (tabs).

**Constraints.**

- Before proposing anything, the engine marks files that **break when moved** and excludes them
  from moves: Steam (and other game) libraries, including ones on other drives; system files;
  caches; files with relative dependencies next to them (e.g. an `.exe` with DLLs beside it,
  HTML with an asset folder, projects with relative paths).
- Moves go through **the same quarantine/journal API as deletions**: journaled in SQLite,
  reversible, re-validated before execution (file changed since scan → move refused).

**Placement.** Separate package `kresorter.organize`, outside the MVP. Reuses `core` (walker,
policy) and `quarantine` (journal, rollback). See `docs/roadmap.md`, step 5.

**Consequences for step 1.** Policy and walker report *why* something is skipped through a
reason enum, so the organizer can later extend reasons with "unsafe to move".
