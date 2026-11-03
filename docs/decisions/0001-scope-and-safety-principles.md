# 0001. Scope, safety principles and tooling

- Status: accepted
- Date: 2026-10-31

## Context

kresorter analyzes user-selected directories and proposes a cleanup plan. Wrongly deleting a
user's file is the worst possible failure, so safety must be enforced by structure and tooling,
not by discipline alone.

## Decisions

1. **Never delete directly.** The only path to removal is the quarantine API (step 2).
   `os.remove`, `os.unlink`, `os.rmdir`, `os.removedirs`, `shutil.rmtree` are banned via ruff
   `banned-api` in `src/` and `tests/`. `Path.unlink` / `Path.rmdir` are method calls ruff cannot
   ban, so `tests/test_no_direct_delete.py` checks the AST of all project code.
2. **Blacklist by default.** Program Files, user profiles, system directories and open files are
   never candidates. Scanning starts from safe zones only.
3. **No registry access** outside the future autostart module (Run/RunOnce only, logged, reversible).
4. **Local only, no telemetry.**
5. **Engine in pure Python, stdlib only for step 1.** No runtime dependencies until needed.
6. **Tooling for step 1:** pytest + coverage ≥ 80% (branch), mypy `--strict`, ruff lint/format,
   CI on Linux only. CRAP, duplicate detection and mutation testing are deferred to a later step;
   pre-commit is deferred too.
7. **Process:** TDD (a failing test is committed before the code that makes it pass), small
   ordered commits, root-cause fixes, decisions logged here.

## Consequences

- Any code path that removes files must be reviewed against the quarantine API.
- Test fixtures rely on pytest's `tmp_path` cleanup instead of deleting files themselves.
