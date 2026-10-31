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

## Target package layout

```
src/safeclean/
├── core/         # step 1: models, policy, walker, hashing, heuristics, open_files, scanner
├── quarantine/   # step 2: move with metadata, restore (used by deletions AND organizer moves)
├── storage/      # step 2: SQLite index and operations journal
├── analysis/     # step 3
├── autostart/    # step 4
├── organize/     # step 5
├── llm/          # step 6
└── ui/           # step 7
```

Directories are created only when their step starts.
