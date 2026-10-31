# 0004. Quarantine, journal and rollback

- Status: accepted
- Date: 2026-10-31
- Builds on: 0001 (no direct deletion), 0003 (open-file check before any action)

## Context

Step 2 introduces the first operations that change the disk. Every one of them must be
journaled, re-validated right before it happens, and reversible.

## Decisions

1. **Journal before move.** A `pending` item row is committed to SQLite *before* the file is
   moved, then marked done. `recover()` runs at startup and reconciles every pending row with
   the disk: file in the vault -> `quarantined`; file at the original path -> rolled back;
   neither -> `lost`, reported loudly and never silently dropped.
2. **SQLite settings.** WAL, `foreign_keys=ON`, `busy_timeout`, `synchronous=FULL`; writes run
   in `BEGIN IMMEDIATE` transactions that roll back on any exception; schema versioned by
   `PRAGMA user_version`; states constrained by `CHECK`.
3. **Rename only, same device.** Files are moved with `os.replace` into a vault on the same
   device. A file on another device (`st_dev` differs) is refused with `CROSS_DEVICE`;
   copy-verify-delete is deferred because it contains a deletion.
4. **Batch is atomic.** If any item of an operation fails, items already moved in that operation
   are moved back and the operation becomes `rolled_back`.
5. **Preflight right before acting** (per item): policy re-check including open files; the
   service refuses to start without an open-file checker with `reliable=True`; `lstat` must be a
   regular file, not a symlink; `size` and `mtime_ns` must equal the scan; the parent directory
   must not have been swapped for a link; for duplicates, the twin that stays must still exist
   with the same digest.
6. **Restore** puts the file back at its original path with mode, mtime and atime. An occupied
   original path is refused with `CONFLICT` (never overwritten); missing parent directories are
   recreated.
7. **Purge** (final deletion) only for quarantined items and only with a one-time confirmation
   object from `plan_purge()`. Purged items cannot be restored; the journal keeps the record.
8. **Single deletion point.** `quarantine/purge.py` is the only file exempt from the deletion
   ban (ruff per-file-ignore and the AST guard allowlist). A test fails if the allowlist grows.
9. **Open-file backends.** Step 2 ships the Linux backend (`/proc/*/fd`). On Windows and macOS
   the quarantine refuses politely until those OSes are in CI (Restart Manager / `lsof` later).
10. **`mtime_ns` instead of float `mtime`** in `FileEntry`: change detection is exact and the
    value round-trips through SQLite without loss.

## The vault is never inside a default scan zone

- The vault lives under the application data directory, never under `~/.cache` or `~/Downloads`:
  - Linux: `$XDG_DATA_HOME/safeclean` (default `~/.local/share/safeclean`)
  - Windows: `%LOCALAPPDATA%\safeclean`
  - macOS: `~/Library/Application Support/safeclean`
- If the resolved data directory (for example, through a custom `XDG_DATA_HOME`) falls inside
  any default scan root or matches a junk rule, the quarantine refuses to start.
- The data directory is also **added to the policy blacklist** (`BlockReason.APP_DATA`), so the
  scanner never lists the vault or the journal, even when the user explicitly scans a parent such
  as `~`. A file in quarantine can therefore never show up as "junk" again.

## Consequences

- Quarantine on Windows/macOS is unavailable in step 2 by design.
- Files on other drives cannot be quarantined in step 2.
- Every later action (organizer moves in step 5) reuses this journal, preflight and rollback.
