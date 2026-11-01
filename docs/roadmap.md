# Roadmap

Each step ends with tests and a commit; the next step starts only after the previous one passes
its checks.

| Step | Module | Content | Release |
|---|---|---|---|
| 1 | `core` | Scanner: walk, hashing, junk heuristics, path blacklist and default safe zones. Console mode. | MVP (iteration 1) |
| 2 | `quarantine`, `storage` | Quarantine with metadata, SQLite journal (WAL, FK, rollback), restore. "File changed between scan and action". Vault outside default scan zones and blacklisted (decision 0004). | MVP (iteration 1) |
| 3 | `analysis` | Duplicates by hash, large/old files, cache patterns, "safe to delete" score. **MVP.** | MVP (iteration 1) |
| 4 | `autostart` | Startup folders, Run/RunOnce (HKCU/HKLM, opt-in setting), task scheduler, auto services. Disable = keep record, never delete. Fake hive in tests. | Iteration 2 |
| 5 | `organize` | File organizer: proposed category structure for a folder; "breaks when moved" detection (Steam libraries, system files, caches, relative dependencies); moves journaled before they happen, in a table of their own, with rollback and recovery; refused on macOS and Windows at first (pre-step-5 audit, decisions 3-4; decision 0012). | Iteration 2 |
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

### Step 4: done
- `autostart` readers, one listing per platform (`autostart.listing`): XDG autostart and
  systemd user units (Linux); Run and RunOnce keys with their `StartupApproved` state, startup
  folders, services and scheduled tasks (Windows, machine-wide only with `--include-machine`);
  launchd agents and daemons (macOS). Every entry has a digest of what was read; unreadable
  entries are skips with a reason, never silence.
- Changes, XDG and `HKCU` Run only (item 8), each journaled in `autostart_changes` (schema v3)
  before anything is written: an own XDG entry is replaced atomically by its `Hidden=true`
  copy with the original kept in the private autostart store; a system entry gets a user
  stub, `/etc` is never written; a Run value gets the Task Manager's `StartupApproved` flag,
  the Run value is never written. Nothing is ever deleted; failures are rolled back and read
  back from the disk or the registry.
- `recover()` per domain closes interrupted changes by what is on disk or in the registry,
  never redoing or undoing; unfinished work in either domain blocks both (`storage.pending`),
  and each domain's `recover()` is never blocked.
- CLI: `safeclean autostart list [--json] [--include-machine]` (read-only, shows `id` and
  `disableable`), `safeclean autostart recover`, `safeclean autostart disable|enable ID
  [--yes]` (preview without `--yes`), sharing the journal session with the quarantine
  (`cli_journal`); exit codes 0/1/2/3 as in the quarantine.
- Decision 0011 with its addenda (items 1-109). 1024 tests, 100 % line and branch coverage.

### Accepted limitations carried into step 5
- Everything from steps 2 and 3 still holds; the open-file check is still Linux-only, which
  blocks the quarantine on macOS and Windows but not autostart changes, which do not need it.
- **Read-only sources** (item 9): systemd user units, RunOnce, startup folders, `HKLM` Run,
  services, scheduled tasks and launchd are listed, never changed; each needs its own risk
  analysis before it can be written.
- **Readers, to revisit after the first live runs** (items 19, 29, 39, 40): systemd drop-ins
  (`<unit>.d/*.conf`), `<target>.requires/` and `/etc/systemd/user` are not read; startup
  folder shortcuts (`.lnk`) are not resolved; trigger-start services are not shown and a shared
  `svchost` service's `ServiceDll` is not read; task boundaries and delays, `TaskCache`,
  launchd overrides, `LimitLoadToSessionType` and `/System/Library` are not taken into account.
- **The registry is tested on a fake only**: `WinRegistry` (read and `set_user_value`) has not
  run on a live Windows yet.
- **No compare-and-swap** (items 69, 85): between the last check and the write an entry can
  still change; the compensation is the same as in the quarantine (journal first, state read
  back, `recover()`).
- **An entry disabled elsewhere cannot be enabled by safeclean** (item 74, `foreign`), and an
  entry that exists but cannot be read blocks autostart changes until the user fixes or moves
  it (item 97).
- **The autostart store is never purged** (item 66): originals, staged copies and removed stubs
  stay in `<data_dir>/autostart`.

### Step 5.0: done (pre-step-5 audit)
- The audit ([`docs/reviews/pre-step5-audit.md`](reviews/pre-step5-audit.md)) and its plan, in
  order, every red test approved before it was committed.
- Gate: 100 % of lines and branches, CI on Python 3.11 to 3.14 (A4).
- Fixes: "missing" is decided by errno (A1); an `OSError` of a command's body is reported by
  its domain, not as the data directory (A2); a journal failure in the middle of a command
  exits with 3 and names the recover command (A3); XDG changes make the store with their first
  change, journal a stub before it is renamed, and roll back when their place is taken (B9
  a-c).
- Refactors without behaviour change: `storage.data_dir` (B1), `autostart.journal` (B2),
  `storage.journal.insert_row()` and a clock given to each domain (B3), `quarantine.journal`
  and `quarantine.recovery`, which needs no open-file check (B7); tests share helpers in
  `tests/support/` and fixtures in `tests/conftest.py` (B10).
- `safeclean recover` closes the interrupted work of every domain, `autostart recover` is its
  alias, and `storage.pending.pending_domains` names the domain whose work is left (B4).
- README: every command, the data directory, recovery and exit codes (A5).
- Decision 0011, items 110-127. 1063 tests, 100 % line and branch coverage.

### Left for later
- B8: one environment object for `cli.main` instead of a factory per parameter.
- B9 (d): no index on `autostart_changes(location)` (skipped, audit decision 5).
- B11: CI on Windows and macOS and live `WinRegistry` tests, once the repository is published.
- B12: a user's own stub without `Exec` that `enable` moved to the store is not given back
  (accepted limitation of step 5).

## Target package layout

```
src/safeclean/
├── core/         # step 1: models, policy, walker, hashing, heuristics, open_files, scanner
├── quarantine/   # step 2: move with metadata, restore, purge, recovery
├── storage/      # step 2: SQLite journal, data directory, lock, unfinished work by domain
├── analysis/     # step 3: duplicates, size_age, score, report
├── autostart/    # step 4: readers, listing, XDG and HKCU Run changes, recover
├── organize/     # step 5: moves journaled in their own table (decision 0012)
├── llm/          # step 6
└── ui/           # step 7
```

Directories are created only when their step starts.
