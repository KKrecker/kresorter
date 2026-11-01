# Roadmap

Each step ends with tests and a commit; the next step starts only after the previous one passes
its checks.

| Step | Module | Content | Release |
|---|---|---|---|
| 1 | `core` | Scanner: walk, hashing, junk heuristics, path blacklist and default safe zones. Console mode. | MVP (iteration 1) |
| 2 | `quarantine`, `storage` | Quarantine with metadata, SQLite journal (WAL, FK, rollback), restore. "File changed between scan and action". Vault outside default scan zones and blacklisted (decision 0004). | MVP (iteration 1) |
| 3 | `analysis` | Duplicates by hash, large/old files, cache patterns, "safe to delete" score. **MVP.** | MVP (iteration 1) |
| 4 | `autostart` | Startup folders, Run/RunOnce (HKCU/HKLM, opt-in setting), task scheduler, auto services. Disable = keep record, never delete. Fake hive in tests. | Iteration 2 |
| 5 | `organize` | File organizer: proposed category structure for a folder; "breaks when moved" detection (Steam libraries, system files, caches, relative dependencies); moves through quarantine with rollback. | Iteration 2 |
| 6 | `llm` | Ollama: local explanations for findings, autostart items and organizer proposals. | Iteration 2 |
| 7 | `ui` | Scan, findings with filters, cleanup plan, organizer, autostart, quarantine/restore, settings (incl. registry opt-in). | Iteration 3 |
| 8 | packaging | Installer, VM tests, README with screenshots. | Iteration 3 |

## Status

### Step 1: done
Scanner core and `safeclean scan` (read-only report).

### Step 2: done
- `storage`: SQLite journal (WAL, foreign keys, `synchronous=FULL`), versioned all-or-nothing
  migrations (schema v2), explicit transactions; single-instance lock on the data directory
  (`flock` / `msvcrt.locking`, released by the kernel on crash).
- `core.open_files`: reliable backend on Linux (`/proc/*/fd`).
- `quarantine`: preflight re-validation, private vault, journal-before-move, atomic batch with a
  rollback that trusts the disk, `recover()`, restore (never overwrites), two-step purge with
  the single deletion point `quarantine/purge.py`.
- CLI: `safeclean quarantine add / list / restore / purge [--yes]`, exit codes 0/1/2/3.
- Decisions 0004-0009. 415 tests, 100 % line and branch coverage.

### Accepted limitations carried into step 3
- **Open-file check is Linux-only.** macOS and Windows have no reliable backend yet: `scan`
  discloses it, every `quarantine` command refuses with exit code 3 (decisions 0005, 0009).
  Backends (e.g. `lsof`/`proc_pidinfo`, Restart Manager) are a separate step before those OSes
  can act.
- **Parallel runs: solved** by the single-instance lock (0009, addendum); `scan` takes no lock
  because it never touches the data directory.
- **Rename race:** the `CONFLICT` check and `Path.replace` are two steps; no no-replace rename
  in the standard library (0007).
- **Empty operation directories stay in the vault** (0008): removing them would need a second
  deletion point.
- **Purge plans live in memory only**: plan and confirmation happen in one process (0008).
- **Quarantine works on files**, not directories; a cross-device file is refused
  (`CROSS_DEVICE`), never copied.

### Step 3: done
- `analysis.duplicates`: which copy of a duplicate group stays (not junk -> outside safe zones
  -> oldest -> shallowest -> path), every other copy a `Candidate` twinned with the keeper; a
  group never loses all copies.
- `analysis.size_age`: large (>= 500 MiB) and old (>= 730 days by `mtime`) files.
- `analysis.score`: levels `SAFE` / `LIKELY_SAFE` / `REVIEW` with pinned evidence and
  user-facing reasons; large/old never raise a level; only `SAFE`/`LIKELY_SAFE` are proposed.
- `analysis.report`: one read-only pass that merges all evidence into one finding per file;
  a kept copy is never proposed, even when it is junk; absolute paths everywhere.
- CLI: `safeclean analyze [paths] [--json] [--large MIB] [--older-than DAYS]` (read-only) and
  `safeclean quarantine add --from-analysis [paths] --level {safe,likely_safe} [--yes]` (plan
  without `--yes`, every file re-checked by preflight at move time).
- Decision 0010 (with the 6b addendum). 512 tests, 100 % line and branch coverage.

### Accepted limitations carried into step 4
- Everything from step 2 still holds; in particular the **open-file check is Linux-only**, so
  `quarantine add --from-analysis` exits with 3 on macOS and Windows, plan included (0010,
  item 18).
- **The plan and `--yes` are two analyses.** Nothing is stored between runs, so the `--yes` run
  re-scans and may differ from the plan shown before (a file appeared, changed or vanished).
  Safety does not depend on it: preflight re-checks every file, and the output lists exactly
  what moved. A stored, signed plan would be a separate decision.
- **Every run re-reads and re-hashes** the roots; there is no hash cache, and the whole report
  (`ScanReport.entries`) is held in memory. Fine for home directories, slow for very large
  trees.
- **Duplicates are exact** (same content hash); no near-duplicates (resized photos, re-encoded
  media). Hard links are left to preflight (`TWIN_SAME_FILE`).
- **Age is `mtime` only**; `atime` is unreliable and never used, so "old" means "unmodified",
  not "unused".
- **Junk rules are static data** (`core/junk_rules.toml`, 14 rules); no user-defined rules yet.
- **`REVIEW` is never moved in bulk**; large/old files go to the quarantine only when named by
  hand (`safeclean quarantine add PATH`).

### Step 4: in progress
Accepted limitations so far (decision 0011, item 19), to revisit after the first live run on
Linux:
- systemd drop-ins (`<unit>.d/*.conf`) are not read: an overridden `ExecStart` is shown as in
  the main unit file;
- `<target>.requires/` is not read;
- units enabled for all users (`/etc/systemd/user`) are not read.

Deferred on Windows (decision 0011, item 29): shortcut (`.lnk`) targets in startup folders are
not resolved; the item's command is the shortcut file itself.

Services (decision 0011, item 39): trigger-start services are not shown; for a shared
`svchost` service `Parameters\ServiceDll` is not read (the user sees the `svchost` entry, not
what it runs); `Group` and `DependOnService` are not taken into account.

Scheduled tasks and launchd (decision 0011, item 40): task `StartBoundary`/`EndBoundary` and
delays are not taken into account and `TaskCache` is not compared with the XML; the launchd
state comes from the file only (`/var/db/com.apple.xpc.launchd/` overrides are root-only and not
read), `LimitLoadToSessionType` is ignored, `/System/Library` is not read.

Done: journal schema v3, `autostart_changes` (commit 11, decision 0011, items 57-62).

Done in commit 12: `xdg_changes` (12a1), XDG disable journaled (12a2, items 66-74), XDG
enable (12a3, items 75-79), `UserRegistry` (12a4a, item 80), the `HKCU` Run `StartupApproved`
flag (12a4b, items 81-87), the exact flag name in the journal (12b1, item 86), `recover()`
for `HKCU` Run changes (12b2, items 88-92), `recover()` for XDG changes (12b3, items 93-98).

Remaining: 12b4 pending autostart changes blocking the quarantine (item 62), 12c the CLI
with `disableable`.

## Target package layout

```
src/safeclean/
├── core/         # step 1: models, policy, walker, hashing, heuristics, open_files, scanner
├── quarantine/   # step 2: move with metadata, restore (used by deletions AND organizer moves)
├── storage/      # step 2: SQLite index and operations journal
├── analysis/     # step 3: duplicates, size_age, score, report
├── autostart/    # step 4
├── organize/     # step 5
├── llm/          # step 6
└── ui/           # step 7
```

Directories are created only when their step starts.
