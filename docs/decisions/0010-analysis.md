# 0010. Analysis: advisory, explainable, deterministic

- Status: accepted
- Date: 2026-10-31
- Builds on: 0001, 0004 (preflight), 0006

## Principles

1. **Analysis only advises and never touches the disk.** `safeclean.analysis` turns a scan
   report into proposals; every proposal is a quarantine `Candidate`, so preflight re-checks it
   right before anything moves, and every action stays reversible until purge.
2. **Every conclusion is explained.** A proposal carries the reasons that produced it; there is
   no verdict without its evidence.
3. **Deterministic.** The same scan gives the same proposals, whatever the input order.

## Duplicates (step 3, commit 1)

4. **Which copy stays.** The keeper is the minimum of a fixed key, in this order:
   1. no junk rule matches it (a cache copy is the expendable one);
   2. it is outside the safe zones (`~/Downloads`, `~/.cache`);
   3. the oldest `mtime_ns` (most likely the original);
   4. the shallowest path;
   5. the first path in sort order (determinism only).
5. **The reason (`KeepReason`) is the first criterion that put the keeper ahead of the
   runner-up**; copies that lost earlier do not affect it. The set of reasons is pinned by a test.
6. **A group never loses all its copies.** Even when every copy is junk, one stays. Deleting
   the last copy is irreversible, and analysis has no right to suggest it.
7. **Every other copy becomes `Candidate(entry, twin=keeper, digest)`**: preflight verifies the
   keeper (present, unchanged, not the same file) before each move.
8. **Hard links are left to preflight** (`TWIN_SAME_FILE`): analysis has no inode data. The
   overlap of protections at two levels is deliberate.
9. **Invalid groups are programming errors** (`ValueError`): fewer than two copies, different
   sizes, the same path twice.
10. **`atime` is never used** (unreliable under `noatime`/`relatime`); age is `mtime_ns`, and
    an `mtime` in the future is not "old".

## Safety levels (decided now, implemented in commit 4)

11. **Levels, not a number.** Three levels with a pinned list of reasons; a 0-100 score would be
    false precision.
    - `SAFE`: junk categories `cache`, `thumbnails`, `os_metadata`;
    - `LIKELY_SAFE`: junk categories `temp`, `crash_dump`; non-kept copies of duplicates;
    - `REVIEW`: large or old files on their own. Never proposed for quarantine automatically.
12. **Combining reasons:** a finding's level is that of its strongest reason. "Large" and "old"
    never raise a level.
13. **`REVIEW` findings list all their reasons**, so the user sees why a file is in the report
    even when nothing is proposed.
14. **Bulk quarantine from an analysis** shows the plan and acts only with `--yes`.
