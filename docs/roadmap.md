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
