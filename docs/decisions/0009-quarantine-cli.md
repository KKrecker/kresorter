# 0009. Quarantine CLI

- Status: accepted
- Date: 2026-10-31
- Builds on: 0004, 0006, 0007, 0008

## Decisions

1. **Commands.** `safeclean quarantine add PATH...`, `list`, `restore ID...`,
   `purge ID... [--yes]` (module `safeclean.cli_quarantine`). `add` takes files only;
   relative paths are made absolute (not resolved: preflight refuses links itself). A missing
   path is passed on and refused by preflight (`not_found`), like every other refusal.
2. **Only `purge` needs `--yes`.** `add` and `restore` are reversible. Without `--yes`, `purge`
   prints the plan (items, total size) and deletes nothing, exit code 1. With `--yes`, plan and
   purge run in the same process (0008). No interactive prompt: the confirmation is explicit
   and testable.
3. **`list` shows `quarantined` items only.** `lost` items are reported by `recover()`
   warnings (stderr), not listed as if they could be restored.
4. **`purge` by ids only**; no `--all` for now.
5. **Exit codes.** 0: everything requested was done. 1: something was refused, not confirmed
   or there was nothing to do. 2: usage error (argparse). 3: unsafe to run: no reliable
   open-file check, data directory inside a scan zone or matching a junk rule, journal cannot
   be opened.
6. **Data directory checked before anything is created.** `check_data_dir()` (shared with the
   service) runs first; only then the directory is created (0700, tightened if loosened) and
   the journal opened at `<data dir>/journal.db`.
7. **Recovery at startup.** Every `quarantine` command runs `recover()` first; recovered items
   are summarised on stdout, `LOST` warnings go to stderr.
8. **No reliable open-file check: every `quarantine` command refuses** (exit 3). The service
   requires the check when it is created, and nothing could have been quarantined there anyway.
9. **`scan` uses `checker_for_platform()`.** On Linux the report is checked for open files; on
   macOS and Windows the missing check is disclosed, as before.
10. **`format_size`/`count` live in `safeclean.text`**, shared by both command modules
    (`cli.format_size` stays importable).

## Addendum (commit 9): single-instance lock

The known limitation above is closed. Two safeclean processes on one data directory (cron,
a double click, a second terminal) would each treat the other's in-flight operation as
interrupted, and the journal would disagree with the disk.

1. **`storage.lock.InstanceLock`** takes an exclusive, non-blocking OS advisory lock on
   `<data dir>/safeclean.lock`: `fcntl.flock` on Linux/macOS, `msvcrt.locking` (first byte) on
   Windows. The lock belongs to the open file, so the kernel releases it when the holder exits
   or crashes: no stale locks, no pid files, no cleanup.
2. **The lock file is created 0600 (tightened if loosened) and never deleted** (0001).
3. **A held lock is `LockedError`** (a `StorageError`); the CLI exits with 3 and changes
   nothing. Order in every `quarantine` command: data directory check -> `mkdir` 0700 ->
   lock -> journal -> `recover()` -> command; the lock is held until the command ends.
4. **`scan` takes no lock**: it never touches the data directory.
5. **`msvcrt` is imported lazily**, so the Windows backend is tested on any OS with a fake
   module, and its import path is covered without `pragma: no cover`.
6. **Error messages split**: "cannot use the data directory" (directory or lock file) and
   "cannot open the journal" (now also catching `sqlite3.Error`, which escaped as a traceback).
