# 0008. Purge: the single deletion point, two-step confirmation

- Status: accepted
- Date: 2026-10-31
- Builds on: 0001 (no direct deletion), 0004 (item 8), 0006, 0007

## Decisions

1. **One function deletes, nothing else.** `quarantine/purge.py::delete_from_vault(vault_root,
   path)` deletes one regular file in a vault slot `<vault>/<operation id>/<item id>`. It refuses
   (`UnsafeDeleteError`) a relative path, a path outside the vault, anything that is not exactly
   two ASCII-digit components below the vault (`..`, wrong depth, other names), an operation
   directory that is a link, and a slot that is a symlink, a directory or any non-regular file.
   A missing slot is a plain `FileNotFoundError`.
2. **`UnsafeDeleteError` is not an `OSError`.** Callers treat `OSError` as a transient failure
   (`DELETE_FAILED`, retry later). An unsafe path means a bug or a tampered journal: it
   propagates, the purge operation stays `pending`, and `recover()` reconciles it.
3. **Links inside the vault are refused; a vault reached through a link is not.** The check
   compares the resolved operation directory with the resolved vault root plus the operation id:
   it protects the object, not the path used to reach it (e.g. a symlinked home).
4. **Guards.** ruff's banned-api stays total, with no per-file ignore: `Path.unlink` is a method
   ruff cannot see. The AST guard (`tests/test_no_direct_delete.py`) now also flags uncalled
   references (`delete = Path.unlink`) and `from os import remove` / `from shutil import rmtree`
   with or without alias. Its allowlist is exactly `purge.py`, pinned by a test; another test
   checks that the allowlisted file really deletes, so a stale entry cannot become a silent hole.
   Growing the allowlist needs a new decision.
5. **Two steps.** `plan_purge(ids)` only reads the journal (refusing unknown, duplicate and not
   `quarantined` items) and returns a `PurgePlan`: items with original path and size,
   `total_bytes`, refusals and a random one-time token. This is what the user confirms.
   `purge(plan)` accepts only a plan issued by the same service instance, unchanged, once. Any
   other plan raises `PurgeError` (a `QuarantineError`); a tampered plan burns its token, so the
   genuine one is refused afterwards too. Tokens live in memory only: a plan does not survive
   the process.
6. **Per-item checks right before deleting**, after the purge operation is journaled `pending`
   and linked via `items.purge_operation_id`: the item must still be `quarantined` (re-checked;
   a restore in between wins), and the vault copy must match the journaled size and `mtime_ns`.
   A changed copy becomes `lost` and is **not deleted** (it is not what the user agreed to
   delete); a missing copy becomes `lost`. An `OSError` from the delete is `DELETE_FAILED` and
   the item stays `quarantined`. Items are independent; the operation is `done`, `failed` or
   `rolled_back`, as for restore (0007). A plan with nothing left to purge journals nothing.
7. **The original path is never touched** by purge, whatever is there now.
8. **Recovery.** For quarantined items of a `pending` purge: an intact vault copy stays
   `quarantined` (the delete never happened), a missing one is `purged` (deleted, journal update
   lost), a changed one is `lost` with a warning. `RecoveryReport.purged` lists the purged ones.
9. **Empty operation directories stay in the vault.** Removing them would need `rmdir`, i.e. a
   second deletion point, for cosmetics only. They are empty, private (0700) and harmless.
10. **Shared code.** Restore and purge share the journal-only selection (`_select`), journaling
    of the side operation (`_journal_side_operation`) and the outcome rule (`_outcome`); restore
    behaviour is unchanged.

## Consequences

- The whole deletion safety argument is one short, auditable function plus the AST guard.
- The CLI (commit 8) must show the plan and require explicit confirmation (`--yes`) before
  calling `purge`, in the same process.
