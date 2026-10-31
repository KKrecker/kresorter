# 0007. Restore: independent items, journaled, recoverable

- Status: accepted
- Date: 2026-10-31
- Builds on: 0004 (item 6), 0006 (recovery trusts only an exact vault copy)

## Decisions

1. **Restore items are independent: deliberate asymmetry with quarantine.** A quarantine batch
   is atomic (one failed move rolls the batch back) because a half-done cleanup is surprising
   and every file stays safe either way. A restore is the user getting files back: undoing the
   restores that succeeded because another item failed would take files away again. Each item
   succeeds or is refused on its own. The operation is `done` (all restored), `rolled_back`
   (none) or `failed` (mixed).
2. **Two stages of checks.** Before journaling: unknown item, the same id twice, not
   `quarantined` (restored, rolled back, lost, purged). If all are refused, nothing is
   journaled. Right before each move, after the restore operation is committed: the vault
   copy, the parent chain, a conflict at the original path.
3. **Never overwrite.** An occupied original path is `CONFLICT`; the item stays `quarantined`.
   The check and `Path.replace` are two steps; the standard library has no no-replace rename,
   so that short window is accepted and documented in the module (no `renameat2` workaround).
4. **A missing or changed vault copy makes the item `lost`** (`VAULT_MISSING`,
   `VAULT_CHANGED`), consistent with 0006: it is never restored as ours.
5. **A parent chain that now contains a link is refused** (`PARENT_SWAPPED`); missing parent
   directories are recreated.
6. **Metadata from the journal.** Mode, atime and mtime are applied to the vault copy first; the
   rename carries them over. Journal schema v2 adds `items.atime_ns` (recorded at preflight);
   v1 rows have `NULL` and keep the vault copy's atime.
7. **Interrupted restores are left to `recover()`.** An `OSError` on one item is `MOVE_FAILED`
   (item stays `quarantined`); any other exception propagates and leaves the operation
   `pending`. `recover()` then decides per item: vault copy intact -> `quarantined`; vault copy
   gone and the file at home matches the journaled size/`mtime_ns` -> `restored`; otherwise
   `lost` with a warning (a different file at home is not taken for ours).
8. **Duplicates on input.** The same path twice in one quarantine batch is refused up front
   (`DUPLICATE_CANDIDATE`); the same item id twice in one restore is `DUPLICATE_ITEM`.

## Consequences

- `RecoveryReport` gains `restored`.
- Purge (commit 7) acts only on `quarantined` items; `restored` and `lost` are never purged.
