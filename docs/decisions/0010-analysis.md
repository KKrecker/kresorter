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

## Addendum (commit 6b): `quarantine add --from-analysis`

15. **`--level` is the least safe level to take**, and it includes the stricter ones:
    `safe` takes `SAFE`; `likely_safe` takes `SAFE` and `LIKELY_SAFE`. `review` is not a
    choice, so `REVIEW` findings are never moved in bulk; kept duplicate copies never are
    either (`Finding.proposed`).
16. **The analysis runs inside the quarantine command**: after the data directory check, the
    single-instance lock and `recover()`, with the default thresholds (they only decide
    `REVIEW`, which is never moved). Without `--yes` the plan is shown and the exit code is 1,
    as for `purge`.
17. **The analysis is not trusted at move time.** Every candidate goes through preflight like a
    hand-picked file: a file opened, changed or replaced since the analysis is refused and the
    rest move (exit 1). Preflight stays the last word.
18. **No reliable open-file check means no bulk add, not even the plan** (exit 3, as for every
    quarantine command). Showing the plan with a warning would be a separate decision.
19. **Usage combinations argparse cannot express** (`--level`/`--yes` without
    `--from-analysis`, `--from-analysis` without `--level`, neither paths nor
    `--from-analysis`) are usage errors with exit 2.
