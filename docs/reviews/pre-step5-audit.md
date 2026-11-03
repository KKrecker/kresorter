# Pre-step-5 audit

- Status: accepted
- Date: 2026-11-01
- Base: `2c15ff5` (step 4 closed), clean tree; the code was not changed by the audit, every
  experiment ran in a throw-away copy
- Leads to: step 5.0 (section 7), then decision 0012 (organize)

## 1. Summary

Step 4 matches decision 0011: items 1-109 are contiguous, and the 46 `item N` references in
`src` all name an existing item on the same subject. The audit found two confirmed defects
(A1, A2), one gap in the exit-code contract (A3), two drifts in configuration and
documentation (A4, A5) and twelve architectural weak spots (B1-B12), most of which get more
expensive once a third domain (organize) exists. They are fixed first, as step 5.0, in small
test/fix pairs and pure refactors.

## 2. Verified

| Check | Result |
|---|---|
| Python 3.11, 3.12, 3.13, 3.14 (uv, throw-away virtual environments) | 1024 passed and 100 % line and branch coverage on each; mypy strict clean on 3.11-3.13 |
| `pragma: no cover` | 3: two `lastrowid is None` guards and one unreachable line in a test |
| `type: ignore` / `noqa` | 1 (`[misc]`, a test of a frozen model) / 0 |
| Safety-critical items 62, 66, 68, 69/85, 71, 90, 97, 103 | each has tests; an unreadable entry is a directory in its place, which holds for root too |
| Direct deletion | ruff banned API plus the AST test; the allowlist is `quarantine/purge.py` only |
| `chmod` as a way to deny access | denies nothing to root (CI containers); in the audit sandbox `chmod 000` on a parent did not deny `stat` to a non-root user either, hence 0011 item 110 |

## 3. Confirmed defects

### A1. Item 97 is broken on Python 3.14 (confirmed by experiment)

`autostart/changes.py::_current()` decides "missing" with `Path.exists()` and
`Path.is_symlink()`. Since Python 3.14 these are `os.path.exists/lexists` and return `False`
for **any** `OSError`; on 3.11-3.13 they raise on `EACCES`. With `os.stat/lstat/open` faked to
raise `PermissionError` for an existing entry:

- 3.11, 3.12, 3.13: `_current` raises `PermissionError` (not the `BrokenEntryError` of item
  97, so the CLI reports it as A2 below);
- 3.14: `_current` returns `None`, "nothing is there".

Consequence: an interrupted disable of a system entry (`before=None`, `after=STUB`) whose stub
exists but cannot be read is closed `rolled_back` by `recover()`: the journal no longer
records the disk. `requires-python = ">=3.11"` has no upper bound, so 3.14 is supported.
`_device()` has the same flaw: on 3.14 a directory that exists but cannot be looked at is
taken for a missing one, and the device of a directory above it is compared with the store.

Fix at the root: "missing" from `lstat`/`stat` with an explicit errno (`ENOENT`, `ENOTDIR`);
anything else is not missing. Tests fake the OS error, independently of the Python version.

### A2. The reason is replaced by "cannot use the data directory" (confirmed by the code)

`cli_journal.with_journal` catches `OSError` around the body of the command too. An `OSError`
reaches it from `_current` (`PermissionError` on 3.11-3.13) in `autostart recover`, `disable`
and `enable`, from `location.rename(slot)` in `XdgChanges._reconcile`, and from `_device()`.
The exit code (3) is right; the reason is wrong, while item 103 promises it.

Fix: the `try` covers the data directory and the lock only; errors of the body are reported by
its domain.

### A3. A `sqlite3.Error` raised by the body is not caught

A full disk or an I/O error during an `INSERT`/`UPDATE` ends in a traceback and exit code 1,
which means "refused, not confirmed or a preview". `main` has no top-level handler.

## 4. Configuration and documentation drift

- **A4.** `pyproject.toml` has `--cov-fail-under=80` and the CI step says "coverage >= 80%",
  while the rule of the project is 100 % of lines and branches: it was held by discipline only.
  The CI comment "Step 1: Linux only" is stale, and 3.12 and 3.14 are not in the matrix,
  although A1 shows that the versions differ.
- **A5.** The README says "steps 1-2"; `analyze` and `autostart list|disable|enable|recover`
  are missing, and exit codes are described for quarantine only.

## 5. Architectural weak spots

| # | What | Why it matters for step 5 | Proposal |
|---|---|---|---|
| B1 | The data-directory policy lives in quarantine: `cli_journal` imports `check_data_dir` and `QuarantineError` from `quarantine.service`, `PRIVATE` from `quarantine.vault` | organize would depend on quarantine for its data directory | `storage/data_dir.py` with `DataDirError` (refactor) |
| B2 | `autostart/changes.py` (404 lines) mixes the store, the journal, the XDG logic and `recover()`; `run_changes.py` imports the journal from the XDG module | layering | `autostart/journal.py`: `Change`, `insert_change`, `finish_change`, `ChangeState`, `ChangeRefusal`, `ChangeResult`, `ChangeRecovery`, `refused` (refactor) |
| B3 | Journal helpers twice (`_insert` in `service.py` and `insert_change`, both with a pragma on `lastrowid`); `time.time_ns()` hard-wired in `service.py` and `changes.py`, while `RunKeyChanges` takes `now` | a third copy in organize | `storage/journal.py`: `insert_row()` and an injected clock |
| B4 | `has_pending` knows two tables; the "go to the other domain" messages are hand-written pairs (`cli_quarantine`, `_outcome` assumes a pending refusal after recover is quarantine's); quarantine has no `recover` and points to `quarantine list` | three domains, six pairs | `pending_domains(conn) -> set[Domain]` and one `kresorter recover` (decision 2) |
| B5 | Growing enumerations in `CHECK` (`operations.kind`, `autostart_changes.source`): SQLite cannot alter a `CHECK` | organize needs a new kind of operation | a table of its own, `moves`, as in item 57 (decision 3) |
| B6 | Decision 0002 §3 says moves go "through the same quarantine/journal API as deletions", but `QuarantineService` is vault-bound (the destination is a vault slot) and needs a reliable open-file check, Linux only | literal reuse does not fit | 0012 amends 0002 §3: the same journal principles and primitives, not the same service (decision 4) |
| B7 | `QuarantineService` cannot be built without a reliable checker, so its `recover()` is unavailable without one, though it does not need it | blocks a common `kresorter recover` | recovery apart from the checker |
| B8 | `cli.main` collects factory parameters (`context_factory`, `autostart_context`, ...) | one more would come | one `Environment` object (platform, env, home, clock, registry factory, checker) |
| B9 | XDG details: (a) `XdgChanges.__init__` creates the store even for a preview or an empty recover; (b) `_create_stub` journals `vault_path` after the rename, `_reconcile` before it, so a crash in between leaves a partial stub in the store that no row names (nothing is lost); (c) `FileExistsError` from `O_EXCL` is `failed` although nothing of ours was touched; (d) no index on `autostart_changes(location)` | honesty of the journal | (a)-(c) small pairs now; (d) skipped (decision 5) |
| B10 | Test helpers repeated: `write` x6, `run` x6, `snapshot` x3, `data_dir`/`scan`/`ctx` x3-4, `query`/`zone` x2; `tests/conftest.py` is empty; tests cite only 14 of the 109 items | organize would add a seventh copy | `tests/support/` with explicit imports; for 0012, every item cited by a test, checked by a meta-test (0011 is not retrofitted) |
| B11 | Windows and macOS code has never run live (`WinRegistry` reading and writing, Run keys, launchd, tasks); CI is Linux only and has not run yet (the repository is not on GitHub) | risk accumulates | once published: Python 3.11-3.14 on Ubuntu, Windows and macOS; live `WinRegistry` contract tests marked `live_windows`, run on a VM |
| B12 | A user's own stub without `Exec` is moved to the store by enable (item 78, by design), but no command gets it back and the store is never purged | — | an accepted limitation of step 5 |

## 6. Decisions

1. **A journal failure in the middle of a command exits with 3**, as the lock and a `failed`
   change do: its end cannot be trusted. A new code 4 would break the 0/1/2/3 contract for no
   gain. Message: `journal failed: <reason>; run '<command> recover'`.
2. **One `kresorter recover` for every domain**; `kresorter autostart recover` stays as an
   alias, since messages of one domain name its own command (12c2, option (b)). B7 separates
   the quarantine's recovery from the checker anyway, and a second command would follow; one
   command and an alias are cheaper than three entry points.
3. **Organize journals into a table of its own, `moves`**, as in item 57: rebuilding
   `operations` under live foreign keys is a risk already rejected once.
4. **Organize refuses on macOS and Windows for a start**, as the quarantine does. Allowing it
   with another check is a later, separate decision: moving from refusal to permission is
   safer than the reverse.
5. **B9 (a)-(c) are fixed now**, each in its own small pair: they concern the honesty of the
   journal, (b) most of all (the journal records the disk). (d) is skipped. B12 is an accepted
   limitation of step 5.
6. **This audit is kept in the repository** as part of the project's history and material for
   0012.

## 7. Step 5.0

In this order; each line is one commit or one test/fix pair, every red test approved before it
is committed:

1. `chore`: `--cov-fail-under=100`, CI matrix 3.11-3.14, stale comment removed (A4). First,
   because it pins the gate every later fix passes through.
2. A1: `_current` and `_device` decide "missing" by errno.
3. A2: `with_journal` narrowed; the body's errors are reported by its domain.
4. A3: journal errors from the body exit with 3 (decision 1).
5. B9 (a)-(c).
6. Refactors without behaviour change: B1, B2, B3 (tests change their imports only).
7. B10: `tests/support/`.
8. B4 and B7: `pending_domains`, `kresorter recover` (decision 2).
9. Documentation: README (A5), roadmap, decision items.

Then the draft of decision 0012 (organize), answering B5 and B6.
