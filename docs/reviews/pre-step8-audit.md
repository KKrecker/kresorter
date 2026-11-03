# Pre-step-8 audit

- Status: accepted
- Date: 2026-11-03
- Base: `22b2622` (step 7's last commit: README and roadmap), clean tree; the code was not
  changed by the audit, every experiment ran in a throw-away copy
- Leads to: step 8.0 (section 7), then step 7 closed (decision 0014 accepted) and the draft of
  decision 0015 (packaging)

## 1. Summary

Step 7 matches decision 0014: items 1-55 are contiguous, each is cited by a test and the
pending list is empty. The window runs its work off its thread as item 15 says, and the wheel
carries everything it needs. The audit found three confirmed defects (A1-A3), three drifts in
configuration and documentation (A4-A6) and six weak spots (B1-B6). A1 breaks item 9 on a
common system, A2 makes the window freeze for seconds to a minute on a large cache folder,
and A3 hides a deprecation that a later PySide6 would turn into a crash. They are fixed first,
as step 8.0; what belongs to a release goes to decision 0015. A3's fix, warnings as errors,
found a fourth defect (A7).

## 2. Verified

| Check | Result |
|---|---|
| Python 3.11, 3.13, 3.14 (the local gate) | 2673 passed and 100 % line and branch coverage on each; ruff, the format and mypy strict clean |
| `pragma: no cover` / `type: ignore` / `noqa` | 2 (`lastrowid is None` in `storage.journal` and one line of a test) / 0 / 0 |
| The wheel (`pip wheel .`) | 138 files: every module, `py.typed`, the 23 icons with Lucide's licence; `kresorter` a console script, `kresorter-ui` a GUI script |
| A fresh virtual environment without the extra | every command runs; `kresorter-ui` and `python -m kresorter.ui` write one line and exit with 3 |
| A fresh virtual environment with `[ui]` (PySide6-Essentials 6.12.0 from PyPI), Linux without `libGL` | a traceback (A1) |
| Work off the window's thread | the 14 `work` functions and the scan's lambda read no widget and no translator; what they return is shown by `done`, in the window's thread |
| 20 000 cache files (`__pycache__`, 200 folders), offscreen | scan and analysis 2.3 s in the worker; then the window's thread: listing 2.0 s, a group's check box 3.5 s, removing what was moved 65 s, the confirmation 6.4 s (A2); search 0.11 s, one check box 0.23 s, a page change 0.03 s |
| The window's smallest size | 1056 x 452 px in English, 1183 x 452 px in Russian (B2) |
| The catalog | 248 texts and 7 counts, keys also built at run time (`change.{action}`); 3 used by nothing (A5) |
| Warnings in a test run | 1398, all one deprecation (A3) |

## 3. Confirmed defects

### A1. A Qt library that cannot be loaded is a traceback (confirmed by experiment)

Item 9 says that when PySide6 cannot be imported, `kresorter-ui` writes one line and returns 3.
`launch.main` tells PySide6's absence from any other import error by `ImportError.name`: only
`PySide6...` and `shiboken6...` give the line, anything else is raised. But when a binding
cannot load a system library (a Linux without `libGL.so.1`, the usual case on a server or a
minimal desktop), the error names the binding alone (`name='QtWidgets'`, `path` its `.so`), so
the user gets a traceback and exit code 1, and nothing says which packages are missing.

On Windows, `kresorter-ui` is a GUI script, which runs without a console: `sys.stderr` is
`None`, so without PySide6 the one line raises `AttributeError` instead (confirmed by the code
and Python's documentation, not run on Windows).

Fix: `main` imports `PySide6.QtWidgets` first. If that fails, Qt cannot be used: when the error
names PySide6 or shiboken6, the line names the extra as today; otherwise it names the error and
the libraries Qt needs on Linux (those of the README); both return 3. The line is written only
when there is a standard error. An import error of the window's own modules is still raised.

### A2. Findings and the confirmation do not scale (confirmed by measurement)

With 20 000 cache files, every change is done item by item, and each item makes the tree's
model announce it:

- listing them takes 2.0 s: each row is inserted into the tree on its own;
- a group's check box takes 3.5 s: each file's check state is a change of its own;
- removing what was moved to the quarantine takes 65 s: `removeChild` row by row, each removal
  making the tree lay itself out again (quadratic: 0.7 s for 2000 files);
- the confirmation takes 6.4 s to open: its details are one `QLabel` of 20 000 lines, laid out
  more than once (0.7 s for 2000).

The window answers nothing meanwhile. A cache folder with tens of thousands of files is
common, so is a Downloads folder with thousands, which organize lists in the same dialog.

Fix: a group's rows are made apart and added in one go; a change to many check states is not
announced row by row, and the rows are drawn again once; what moved is taken out per group,
and the rest put back in one go; the details are a read-only plain-text box (as high as its
lines, up to eight, then it scrolls), which lays out only what is shown.

### A3. A deprecated call, 1398 times per test run

`QTreeWidgetItem.setTextAlignment(int, int)` is deprecated in PySide6 6.12; six lines pass an
`int` (`_RIGHT = int(...)` in Findings, Quarantine and Organize). Nothing turns a warning into
an error, so the gate does not see it, and a PySide6 that removes the overload, which `<7`
allows, would fail when the window opens.

Fix: an alignment flag, and warnings are errors in the tests (`filterwarnings = ["error"]`).

### A7. A refused answer's socket is left to the garbage collector (found by A3's fix)

With warnings as errors, a few tests of `llm` fail at random, each run others, on a
`ResourceWarning: unclosed <_DeadlineSocket [closed]>`. `transport.request` closes the
connection in every case, but with `Connection: close` the connection hands its socket to the
response, and the response is closed only when it is read to its end. A redirect, a
`Content-Length` over the limit and an answer that goes on past the limit are refused without
that, so the socket stays open as long as the failure is kept, then until the garbage collector
finds it. Nothing is read from it or sent on it any more; it is a file descriptor held for no
use.

Fix: the response is closed on every way out of `request`.

## 4. Configuration and documentation drift

- **A4.** `pyproject.toml` says `license = { text = "MIT" }` and the README's last section
  "MIT", but the repository has no licence text, nor does the wheel (only Lucide's, for the
  icons). The metadata has no authors, no URLs and no classifiers; the version is `0.0.1` in
  two places (`pyproject.toml` and `kresorter.__version__`), and no command prints it.
- **A5.** Three entries of the catalog are used by nothing: `overview.folder` (by a test
  only), `overview.folders` and the count `batch`, left from the pages before items 45-55.
- **A6.** `CHANGELOG.md` is the log of the development: 108 entries under `[Unreleased]`,
  some describing what was replaced since (Findings with the columns Path, Level and Size,
  Autostart's Disable and Enable buttons), not in order (`kresorter scan`, the first, is the
  last of `Added`). A first release needs a section that says what it has.

## 5. Weak spots

| # | What | Why it matters for step 8 | Proposal |
|---|---|---|---|
| B1 | The window has run on Linux only, offscreen; on Windows and macOS it never opened, and their autostart writers never ran live (pre-step-5 B11). A GUI script on Windows has no standard error, so the reasons of A1 and any uncaught exception go nowhere | an installer for those systems ships what was never seen there | VM tests in step 8 (decision 0015); what a GUI script cannot write is shown in a dialog |
| B2 | The window cannot be narrower than 1056 px (English) or 1183 px (Russian): Findings' bar (its three Select links) with the detail at its right | 1366 x 768 at 125 % gives 1093 logical px, so the Russian window is wider than the screen there | an accepted limitation of step 8; the README states the width |
| B3 | Read-only accessors used by the tests only (`AutostartPage.switch`, `OrganizePage.batch_row`, `OverviewPage.chips`, `Sidebar.current_list`, `marked`, `count_of`) | none | accepted: they read the state the tests check, and change nothing |
| B4 | The meta-test of a decision is copied three times (0012, 0013, 0014), the copies differing in the decision's number, file and item only; `_child` is defined five times in the window's tests, the same each time | 0015 would make a fourth copy | `tests/support/decisions.py` and `support.window.child` (refactor) |
| B5 | The development tools have lower bounds only (`ruff>=0.5`, `mypy>=1.10`, `pytest>=8`) | a new ruff or mypy can fail CI with no change in the project, on the release's tag too | decision 0015 |
| B6 | No release yet: A4 and A6, no build of the release, nothing published | step 8 | decision 0015 |

## 6. Decisions

1. **A1-A3 and A5 are fixed now**, as step 8.0, before step 7 is closed; A1 extends 0014 item
   9 to Qt's libraries in the decision itself, which is still proposed.
2. **A2's tests count what the tree's model announces, not seconds**: a timing in a test is
   noise on a shared runner. The 20 000 files are measured again after the fix, and the result
   is recorded in the roadmap.
3. **Warnings are errors in the tests**: a dependency's deprecation fails the gate when it is
   announced, not when the dependency removes what it deprecated.
4. **B2 and B3 are accepted**; B2 is stated in the README.
5. **A4, A6, B1, B5 and B6 go to decision 0015** (packaging), with the questions only the
   owner of the project can answer.
6. **This audit is kept in the repository**, as the pre-step-5 audit is.

## 7. Step 8.0

In this order; each line is one commit or one test/fix pair (red, then green):

1. A7, then A3: a request closes its response; warnings are errors, the columns' alignment a
   flag. First, because it pins the gate every later fix passes through.
2. A1: `launch.main` imports Qt first; a library Qt cannot load is one line and exit 3; no line
   without a standard error.
3. A2: the confirmation's details in a plain-text box; then Findings: rows made apart and
   added in one go, check states changed without an announcement per row, what moved taken
   out per group.
4. Refactor without behaviour change: A5's three entries leave the catalog.
5. Refactor of the tests: B4.
6. Documentation: the README (B2), the roadmap; step 7 closed, decision 0014 accepted.

Then the draft of decision 0015 (packaging), answering A4, A6, B1, B5 and B6.
