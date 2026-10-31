# 0006. Quarantine service: batch, rollback and recovery details

- Status: accepted
- Date: 2026-10-31
- Builds on: 0004 (quarantine, journal and rollback), 0005 (Linux open-file backend)

## Decisions

1. **Preflight refusals do not sink the batch.** Refused candidates are reported with their
   reason and left alone; the cleared ones form one atomic operation. If everything is refused,
   no operation is journaled.
2. **`CROSS_DEVICE` is a `RefusalReason`**, checked by the service against the vault's `st_dev`.
3. **Moves are injectable** (`move`, default `Path.replace`); the same function moves files back.
4. **Rollback never overwrites.** If a file appeared at the original path, or moving back fails,
   the item stays `quarantined` (restorable later) and the operation is `failed`; otherwise it is
   `rolled_back`. `OSError` is reported in the result; any other exception (including
   `KeyboardInterrupt`) is re-raised after the rollback.
5. **`recover()` is explicit** (the CLI runs it at startup). While any operation is `pending`,
   new operations are refused.
6. **Recovery trusts only an exact vault copy.** A pending item whose vault file matches the
   journaled size and `mtime_ns` is `quarantined`; a vault file that differs is `lost` with a
   loud warning and is never restored or purged as ours; no vault file and the original in place
   is `rolled_back`; found nowhere is `lost` with a warning. A vault copy wins over a file at the
   original path (rename is atomic, so that file is a newcomer).
7. **Vault permissions.** The data directory, `quarantine/` and each operation directory are
   0700; looser existing permissions are tightened at startup.
8. **Refuse to start** when the data directory is inside a default scan root or matches a junk
   rule (probed as `<data_dir>/quarantine/0/0`).
9. **Default data directories stay blocked** (`~/.local/share/safeclean`,
   `%USERPROFILE%\AppData\Local\safeclean`) when `XDG_DATA_HOME` / `LOCALAPPDATA` point
   elsewhere, so a vault left behind never becomes scannable.

## Consequences

- Restore (commit 6) and purge (commit 7) act only on `quarantined` items; `lost` is final
  until a human looks at it.
- Preflight is not atomic with the rename; journal-before-move and `recover()` cover that window.

## Addendum (commit 8a): the disk decides, not the in-memory list

Found while writing the CLI tests: an interrupt (`KeyboardInterrupt`) can arrive after
`Path.replace` has renamed a file into its slot but before the service records it as moved.
Rollback then marked the item `rolled_back` while the file sat in the vault with its original
path empty: invisible to `recover()`, `restore()` and the user at the same time.

1. **Rollback asks the disk.** An item whose vault slot exists is treated as moved and is moved
   back (newest first, never overwriting), whatever the in-memory list says. The slot belongs to
   a fresh operation directory, so its existence can only mean our rename happened.
2. **`recover()` also reconciles quarantined items of a `pending` quarantine operation**
   (an interrupt during the rollback itself, after a move back but before its journal update):
   - intact vault copy: stays `quarantined`, not reported again;
   - no vault copy and the original matches the journaled size/`mtime_ns`: `rolled_back`;
   - anything else: `lost`, with a warning.
