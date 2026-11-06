# Roadmap

Each step ends with tests and a commit; the next step starts only after the previous one passes
its checks.

| Step | Module | Content | Release |
|---|---|---|---|
| 1 | `core` | Scanner: walk, hashing, junk heuristics, path blacklist and default safe zones. Console mode. | MVP (iteration 1) |
| 2 | `quarantine`, `storage` | Quarantine with metadata, SQLite journal (WAL, FK, rollback), restore. "File changed between scan and action". Vault outside default scan zones and blacklisted (decision 0004). | MVP (iteration 1) |
| 3 | `analysis` | Duplicates by hash, large/old files, cache patterns, "safe to delete" score. **MVP.** | MVP (iteration 1) |
| 4 | `autostart` | Startup folders, Run/RunOnce (HKCU/HKLM, opt-in setting), task scheduler, auto services. Disable = keep record, never delete. Fake hive in tests. | Iteration 2 |
| 5 | `organize` | File organizer: proposed category structure for a folder; "breaks when moved" detection (Steam libraries, system files, caches, relative dependencies); moves journaled before they happen, in a table of their own, with rollback and recovery; refused on macOS, which has no open-file check yet (pre-step-5 audit, decisions 3-4; decision 0012; on Windows since decision 0017). | Iteration 2 |
| 6 | `llm` | Ollama: local explanations for findings, autostart items and organizer proposals. | Iteration 2 |
| 7 | `ui` | Scan, findings with filters, cleanup plan, organizer, autostart, quarantine/restore, settings (incl. registry opt-in). | Iteration 3 |
| 8 | packaging | Kresorter 0.1.0: the Windows installer and portable zip, the wheel on PyPI, CI on Windows, a release from a tag, runs on clean machines, README with screenshots. | Iteration 3 |

## Status

### Step 1: done
Scanner core and `kresorter scan` (read-only report).

### Step 2: done
- `storage`: SQLite journal (WAL, foreign keys, `synchronous=FULL`), versioned all-or-nothing
  migrations (schema v2), explicit transactions; single-instance lock on the data directory
  (`flock` / `msvcrt.locking`, released by the kernel on crash).
- `core.open_files`: reliable backend on Linux (`/proc/*/fd`).
- `quarantine`: preflight re-validation, private vault, journal-before-move, atomic batch with a
  rollback that trusts the disk, `recover()`, restore (never overwrites), two-step purge with
  the single deletion point `quarantine/purge.py`.
- CLI: `kresorter quarantine add / list / restore / purge [--yes]`, exit codes 0/1/2/3.
- Decisions 0004-0009. 415 tests, 100 % line and branch coverage.

### Accepted limitations carried into step 3
- **Open-file check is Linux-only.** macOS and Windows have no reliable backend yet: `scan`
  discloses it, every `quarantine` command refuses with exit code 3 (decisions 0005, 0009).
  Backends (e.g. `lsof`/`proc_pidinfo`, Restart Manager) are a separate step before those OSes
  can act.
- **Parallel runs: solved** by the single-instance lock (0009, addendum); `scan` takes no lock
  because it never touches the data directory.
- **Rename race, Linux only:** the `CONFLICT` check and the rename are two steps; no
  no-replace rename in the standard library (0007). On Windows `Path.rename` refuses a file
  that arrived in between (0016).
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
- CLI: `kresorter analyze [paths] [--json] [--large MIB] [--older-than DAYS]` (read-only) and
  `kresorter quarantine add --from-analysis [paths] --level {safe,likely_safe} [--yes]` (plan
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
  hand (`kresorter quarantine add PATH`).

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
- CLI: `kresorter autostart list [--json] [--include-machine]` (read-only, shows `id` and
  `disableable`), `kresorter autostart recover`, `kresorter autostart disable|enable ID
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
- **An entry disabled elsewhere cannot be enabled by kresorter** (item 74, `foreign`), and an
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
- `kresorter recover` closes the interrupted work of every domain, `autostart recover` is its
  alias, and `storage.pending.pending_domains` names the domain whose work is left (B4).
- README: every command, the data directory, recovery and exit codes (A5).
- Decision 0011, items 110-127. 1063 tests, 100 % line and branch coverage.

### Step 5: done (organize)
- Decision 0012: sort one folder by kind, journaled, reversible, never overwriting; every item
  cited by a test, the meta-test's pending list empty.
- `core.preflight`, shared by the quarantine and organize; schema v4 (`move_batches`, `moves`
  with the file's device and inode) and `Domain.ORGANIZE`.
- `organize`: the category table and the folder markers as data, the platform table, the
  read-only planner (the folder refused as a whole, every file that stays with its reason), the
  mover (checked again, journal first, rename only, all or nothing), recovery by the file's
  identity, undo as a batch of its own.
- CLI: `kresorter organize move FOLDER [--yes]`, `organize list`, `organize undo BATCH
  [--yes]`; `move` and `undo` refuse on macOS and Windows, and on Linux when the open-file
  check is not reliable, before the journal is opened; `kresorter recover` closes organize's
  batches too, on every system. `ScanContext.platform`, required, is the system a context was
  made for, and the refusal reads it.

### Accepted limitations carried into step 6
- Everything from steps 2 to 4 still holds.
- **Organize** (decision 0012): one level only; a taken name is not renamed; empty category
  directories stay after undo; the plan and `--yes` are two passes; the category table is fixed
  and English; dependencies are recognized by markers and names only; Linux only until each
  blocker of item 38 is lifted by its own decision; a device or inode renumbered by a remount
  leaves a move `failed` for the user; folders watched by a sync client on Linux are sorted like
  any other.

### Step 6: done (llm)
- Decision 0013: optional explanations from a local Ollama of what kresorter has already
  decided, advisory and never acted on; every item cited by a test, the meta-test's pending
  list empty.
- `llm.settings`: the address, loopback only (`localhost`, `127.0.0.0/8`, `[::1]`), and the
  model, from the environment; anything else refused before any connection.
- `llm.transport`, the one network point (pinned allowlist): `http.client` on a socket of its
  own, no resolver, no proxy, no redirect, one deadline per request, bounded request and
  answer.
- `llm.client`: exactly three requests (`version`, `tags`, `generate`), `status`'s checks, the
  only accepted answer, the reasons explanations are missing (`Unavailable`); `llm.prompt`,
  the pinned instruction; `llm.clean`, the answer cleaned and bounded before it is shown.
- `llm.subjects`: the facts per kind (finding, autostart entry, file that stays), nothing of
  the files; one subject per set of facts. `llm.explain`: at most 20 per run, stopping at the
  first failure, no connection when there is nothing to explain.
- CLI: `kresorter llm status` (exit 0 or 1) and `--explain` on `analyze`, `autostart list`
  and `organize move` without `--yes`: same stdout and exit code, the explanations after the
  command's own output (text) or in four added keys (JSON), one line on stderr when they are
  missing. Guards: no program launched, one network point, what `llm` imports, no file opened
  by `llm`, no test leaving loopback.
- README: the section `AI explanations (optional)`. 2103 tests, 100 % line and branch
  coverage.

### Accepted limitations carried into step 7
- Everything from steps 2 to 5 still holds.
- **Explanations** (decision 0013): English only, and the model can be wrong; nothing is
  cached, so each run asks again; at most 20 subjects per run, one at a time, without
  streaming; `localhost` is `127.0.0.1`, so an Ollama listening only on `::1` needs
  `KRESORTER_OLLAMA_URL=http://[::1]:11434`; anything listening on the port that answers like
  Ollama is believed to be it (it gets only the facts and its answer is untrusted text); names
  steer the model, never a level, a plan or an action; the default model may be missing, and
  kresorter never installs it.

### Before step 7
- Refactor without behaviour change (B8): `cli.main` takes one `Environment`
  (`kresorter.environment`: the scan and autostart contexts, the settings environment of `llm`
  and its limits) instead of a factory per parameter; `detect_platform` and `default_context`
  live there, so the CLI and the UI make the same contexts.

### Step 7: done (ui)
- Decision 0014: an optional desktop window over the services the CLI runs, report first and
  every action confirmed; every item cited by a test, the meta-test's pending list empty.
- Refactor first, without behaviour change: the journal session in `storage.session`,
  `analysis.run`, `autostart.changers` and `quarantine.journal.quarantined`, which the CLI and
  the window share.
- The extra `ui` (`PySide6-Essentials`), `kresorter-ui` and `python -m kresorter.ui`
  (`ui.launch`); without PySide6 one line and exit 3. The core still depends on nothing and no
  module outside `kresorter.ui` imports Qt; the window imports only `QtCore`, `QtGui` and
  `QtWidgets`, no CLI module, and reaches the network only through `llm`.
- `ui.i18n`, `ui.texts`, `ui.labels`: English and Russian, counts in each language's forms, a
  label for every value shown. `ui.theme`: the tokens, their contrast, light and dark as the
  system says. `ui.settings`: `settings.json` alone, written only on a change, a broken file
  not used.
- `ui.tasks` and `ui.window`: one task at a time in a worker thread; closing waits for what
  acts. Pages: `ui.overview`, `ui.findings`, `ui.quarantine`, `ui.organize`, `ui.autostart`,
  `ui.settings_page`; `ui.dialogs` (confirmation, folder), `ui.sessions` (each action in its
  domain's session, plans made again under the lock), `ui.recovery` (the banner and Recover),
  `ui.explain` (Explain (local AI) on request), `ui.app`.
- Tests: `pytest-qt` offscreen with the real worker thread, no live system, and the window and
  the CLI compared on the same trees. 2493 tests, 100 % line and branch coverage.
- Then decision 0012 accepted as it is, and organize's categories named in the window's
  language (0014 item 44): a plan's group shows the label and, in Russian, the directory beside
  it; the directories, every path, the journal and the CLI keep the English names. 2500 tests,
  100 % line and branch coverage.
- Then the prototype's look (0014 items 45-55), page by page: Lucide's icons (`ui.icons`, ISC
  licence), the parts every page is made of (`ui.parts`: heads, cards, chips, badges, fields,
  check boxes, switches, rows of 44 px), the sidebar with its status lines, Overview's cards,
  the confirmation, Findings with its detail and the explanation card, Quarantine, Organize's
  category cards and recent batches, Autostart's switches and search, Settings' cards; how a
  path and a moment are shown (`ui.shown`). Light and dark, English and Russian, every margin on
  the grid. 2673 tests, 100 % line and branch coverage.

### Step 8.0: done (pre-step-8 audit)
- The audit ([`docs/reviews/pre-step8-audit.md`](reviews/pre-step8-audit.md)) and its plan, in
  order, each red test before its fix.
- Fixes: a library Qt cannot load (`libGL.so.1`) is one line and exit 3 instead of a traceback,
  and a GUI script without a standard error writes nothing (A1, decision 0014 item 9); Findings
  adds a group's rows with it, changes many check states at once and takes what moved out in
  one go, and the confirmation's details are plain text (A2; with 20 000 cache files,
  offscreen: listing 2.0 s to 1.0 s, a group's check box 3.5 s to 0.3 s, removing what moved
  65 s to 0.1 s, the confirmation 6.4 s to 0.1 s); the columns' alignment is a flag, and a
  warning fails the tests (A3); a request to Ollama closes its answer on every way out (A7).
- Refactors without behaviour change: three texts nothing shows leave the catalog (A5); the
  meta-tests of decisions 0012 to 0014 share `tests/support/decisions.py`, and the window's
  tests `support.window.children` (B4).
- Step 7 closed: decision 0014 accepted. 2676 tests, 100 % line and branch coverage.

### Accepted limitations carried into step 8
- Everything from steps 2 to 6 still holds.
- **The window's width** (pre-step-8 audit, B2): at least 1056 px in English and 1183 px in
  Russian, for Findings' bar and the detail beside it.
- **Window** (decision 0014): a task cannot be cancelled, and a scan that only reads is left
  behind when the window closes; the folders added on Overview are not remembered; a new
  language applies the next time the window opens; organize's category directories keep their
  English names on disk (only their labels are translated), and the model answers in its own
  words, in the Russian window too; the machine scope is read only on Windows and only listed,
  as with `--include-machine`; the window is tested offscreen on Linux only (B11), with no
  screen reader; there are no screenshots yet (step 8).

### Step 8: done (packaging)
- Decision 0015: the project is Kresorter; one version, `kresorter.__version__`, which
  `kresorter --version` and the Settings page show; the MIT licence in the repository and in
  every artifact, and the metadata; one wheel for every system and the sdist that makes it,
  installed offline and uninstalled by the tests, with nothing of Qt; the tools of the extra
  `dev` pinned. On Windows a GUI program has no console: the line of exit 3 is a message box
  and an uncaught error a dialog (B1). `kresorter-ui --self-test REPORT` shows each page and
  changes nothing, and Kresorter's own folders are never findings (`app_program`).
- Then decision 0016, by its own plan: the Windows open-file check, an exclusive open closed at
  once, and with it the quarantine on Windows; decision 0017: organize on Windows, renames tried
  again after a sharing violation, a path limit of 259 characters, and the folders a sync
  client keeps refused.
- CI on two systems: `ubuntu-latest` for every Python, `windows-latest` for 3.11 and 3.14
  while the repository was private and for every Python since it is public (B11 for the
  checks), and what Windows does otherwise fixed, each with its test: files opened with
  `O_BINARY`, modes as Windows shows them, 100 ns steps, a name in another case.
- The Windows application (`packaging/windows`): PyInstaller's folder `Kresorter` with
  `Kresorter.exe`, its icon and version resource, `LICENSE`, `THIRD-PARTY-NOTICES.txt` and
  Qt's libraries as files of their own; the portable zip, and the Inno Setup installer for the
  current user.
- The artifacts built once, after the checks, and run: `packaging/trial.py` installs the wheel
  in a new environment, runs the installer silently, unzips the portable zip, runs each
  self-test and uninstalls. Only a tag publishes: `packaging/release.py` checks it against
  `__version__` and the changelog, then the wheel and the sdist go to PyPI by trusted
  publishing and a GitHub release gets them with the installer, the zip and `SHA256SUMS.txt`.
- The screenshots, made by `tests/support/screenshots.py` on a made-up home; the changelog of
  0.1.0, for its users; the README's Install, Windows first.
- The release record (0015 item 28): `packaging/release.py check` refuses the tag without
  `docs/releases/<version>.md`, the owner's runs on Windows 10, Windows 11 and an Ubuntu LTS,
  each saying what was done and seen, and names every gap; the form is in
  [`docs/releases/README.md`](releases/README.md).
- 3027 tests, 100 % line and branch coverage. Left before the tag: CI's runs read on both
  systems, Python 3.14 with them (step 6 was checked on it locally only); the owner's runs on
  clean machines and their record; then the tag, by the owner.

### Accepted limitations carried after step 8
- Everything from steps 2 to 7 still holds. The window is now tested offscreen on Windows too,
  and the README has its screenshots.
- **Unsigned** (0015): SmartScreen warns before the installer and `Kresorter.exe` run; signing
  is a later decision.
- **The Windows application is the window**: the commands come with `pipx install kresorter`.
- **No macOS build**, no CI on macOS, and macOS is not claimed by the metadata; the quarantine
  and organize refuse there.
- **No Flatpak, no Snap.**
- **The Windows open-file check** (0016): a handle for attributes only and a file mapped into
  memory after its handle was closed are not seen; a file on another drive than the data
  directory is refused (`cross_device`).
- **Organize on Windows** (0017): Desktop and Documents moved into OneDrive are not sorted; a
  folder synced by a client that registers no Cloud Files root and is not OneDrive is sorted,
  and the client syncs the moves; a file whose new path would pass 259 characters stays, with
  `LongPathsEnabled` too; a file held for more than three seconds stops the batch. The
  quarantine does not ask the synced folders: a junk file in one goes to the vault, which the
  client syncs as a deletion until it is restored.

### Decision 0018: done (the owner's requests)
- [Decision 0018](decisions/0018-owners-requests.md): the owner's thirteen requests after
  step 8, by its plan of sixteen steps, each a test and then its fix.
- The window: a theme, System, Light or Dark, applied at once; a new language offers a restart
  in the same process, on the same page; Select all and Clear in the quarantine; motion (a page
  fades in, a switch slides, hover, a scan's bar and progress), none when its duration is 0; a
  list ringed only when the keyboard focused it; a safe zone left out and put back,
  remembered in `settings.json`.
- What a cache is: a cache likely safe, a browser's cache for review in a category of its own,
  `browser_cache`, named in both languages.
- Speed: one look at `/proc` per scan, the rules matched and the policy asked once per
  directory, Windows' share-mode checks and the hashing side by side, and the scan's
  progress; a scan of 20 000 files on Linux went from 6.1 s to about 1.5 s.
- The local AI: the model chosen in Settings among those Ollama has, one recommended for the
  machine's memory and processors (`llm.machine`), named in the sidebar and on the Overview's
  Local AI card; grouping by meaning on the Organize page (`llm.group`): the names only, one
  bounded answer checked as untrusted input, a plan made by the planner, By kind to go back,
  Sort without asking again.
- The security audit, [`reviews/security-audit.md`](reviews/security-audit.md): every label
  plain text and every tooltip escaped; nothing in `src` runs text; `settings.json` read with at
  most 64 KiB, never through a link, a FIFO refused without waiting; the lock refuses a link;
  the transport refuses an address off loopback.
- 3400 tests, 100 % line and branch coverage.

### Accepted limitations of decision 0018
- Everything carried after step 8 still holds.
- **The scan's look at `/proc` is a moment**: a file opened during a long scan is reported as
  not open; preflight checks it again before anything acts.
- **A browser's cache is never proposed**, though the browsers say it holds no sign-ins: the
  owner's choice, for the time and traffic it costs.
- **The model can be wrong**: a group may not fit its files; the plan is shown before anything
  moves, and every batch can be undone.
- **The names leave kresorter for the model**, on loopback only, when the user asks: the model
  and Ollama are the user's own.
- **The recommendation is a rule of thumb** for memory and processors; it reads no graphics
  card.

### Decision 0019: done (the owner's requests, second round)
- [Decision 0019](decisions/0019-owners-requests-2.md): the owner's six requests after using
  the Windows build, by its plan of ten steps, each a test and then its fix.
- The answers' language: the instruction names it, the window's (`system` resolved) or English
  on the console, and asks to speak of the item, not of the JSON object; a reasoning model's
  `<think>` block is dropped before the answer is cleaned.
- The icon: `ui.brand` draws the mark and makes of it the application's icon, 16 to 256 px, set
  before the first window opens; the ICO of `Kresorter.exe` and of the installer is made from
  the same drawing.
- LM Studio beside Ollama (`llm.lmstudio`): `KRESORTER_LLM_SERVER`, `KRESORTER_LMSTUDIO_URL` and
  `KRESORTER_LMSTUDIO_MODEL`; exactly two requests, `GET /v1/models` and
  `POST /v1/chat/completions`, a grouping's answer bound by a JSON schema; `llm status` and the
  explanations' header name the server; in the window, the Server choice on the Settings page,
  saved in `settings.json` as `server`, and the recommendation as LM Studio names it.
- The README in Russian, `README.ru.md`, kept with `README.md` by a test: the switch under each
  title, the same headings, code blocks, images and link targets.
- The release: the GitHub release `Kresorter X.Y.Z` first, PyPI after it only when the
  repository's variable `PUBLISH_TO_PYPI` is `true`; the changelog dated the day of the tagged
  commit; 0.1.0 in the files' names and the version resources.
- The licence shown: the installer's `LicenseFile`, the Settings page under the version, and the
  README's License section in both languages.
- 3669 tests, 100 % line and branch coverage.

### Accepted limitations of decision 0019
- Everything of decision 0018 still holds.
- **A small model may still answer in another language**: the instruction asks; the answer is
  advisory and says it may be wrong.
- **LM Studio's first model is a guess** when none is chosen: an embedding model whose id does
  not say `embed` is taken, and its answer is refused as `http_status` or `bad_response`.
- **LM Studio says no version**: its line says only that it runs.
- **The executable is not signed**: Windows SmartScreen may warn the first time; signing needs
  a code-signing certificate, which the project does not have.
- **The screenshots are the English window's**, in `README.ru.md` too.
- **PyPI is the owner's to turn on**: until it is, the wheel and the sdist come from the GitHub
  release.

### Decision 0020: done (the owner's requests, third round)
- [Decision 0020](decisions/0020-owners-requests-3.md): the owner's four requests after using
  the Windows build (a grouping that was not read, more sorted by kind, a cleanup that keeps
  every session, a faster scan), by its plan of nine steps, each a test and then its fix.
- A grouping that is read: the names in numbered batches, at most 40 and 2,000 bytes each and
  at most 10 (400 names), a batch with its instruction and its answer within 4096 tokens; the
  answer's JSON schema asked of Ollama (`format`) and of LM Studio (`response_format`),
  `"think": false` for Ollama and `/no_think` for LM Studio; the answer read from a fenced block
  or between its braces too, a cut one said; the folders of the batches before passed on; a
  batch that fails keeps the groups before it, and the note says how many files were grouped.
  Qwen3 recommended, in both servers' names.
- More kinds: the table's extensions, and `Torrents`, `Fonts` and `3D models` after the others.
- The sessions: `core/sessions.toml` read by `core.sessions`, blocked for a reason of their own,
  `session`, each pattern found by the last name it writes out, a folder's once; Windows'
  upgrade folders (`Windows.old`, `$Windows.~BT`, `$Windows.~WS`) blocked at the drive's root.
- The caches: the graphics drivers' and the browsers' shader caches, Windows Error Reporting's
  reports; on Windows the zone of programs' caches, `caches`, read for junk only.
- The scan: the walk opens no file; the junk and the copies are checked for being open once
  they are known; the window keeps the digests (`core.hashing.Digests`); the Findings page says
  the times (`ScanTimes`). No MFT: on a GitHub Windows runner, 190,433 files were listed in
  2.2 s and scanned in 9.8 s without the open-file check, in 32.9 s with it on every file, and
  reading the MFT of C:, 1.36 million records, took 15 s as an administrator.
- 4057 tests, 100 % line and branch coverage.

### Accepted limitations of decision 0020
- Everything of decision 0019 still holds.
- **A small model still groups less**: the batches and the numbers make its answer short and
  readable, not wise; the plan is shown before anything moves and a batch can be undone.
- **A grouping takes longer**: up to 10 requests instead of one, each short.
- **A file kept open by a program is found by a scan** when it is neither junk nor a
  duplicate (a large or old one, shown for review): the check comes when it is acted on.
- **Digests are kept in memory only**: the first scan after the window opens hashes again.
- **Firefox and the other browsers' session lists are by name**: a browser that adds a store
  of its own is not protected until the list says so.
- **The system's own folders are Windows' to clean**: Settings > System > Storage, or Disk
  Cleanup.
- **No MFT**: a scan of a large folder still lists it directory by directory.

### Left for later
- B9 (d): no index on `autostart_changes(location)` (skipped, audit decision 5).
- B11: CI on macOS, and live `WinRegistry` tests.
- B12: a user's own stub without `Exec` that `enable` moved to the store is not given back
  (accepted limitation of step 5).

## Target package layout

```
src/kresorter/
├── core/         # step 1: models, policy, walker, hashing, heuristics, open_files, scanner;
                  #   preflight (0004); sessions (0020)
├── quarantine/   # step 2: move with metadata, restore, purge, recovery
├── storage/      # step 2: SQLite journal, data directory, lock, unfinished work by domain
├── analysis/     # step 3: duplicates, size_age, score, report
├── autostart/    # step 4: readers, listing, XDG and HKCU Run changes, recover
├── organize/     # step 5: categories, planner, mover, journal, recovery, undo (decision 0012)
├── llm/          # step 6: settings, transport, client, prompt, clean, subjects, explain,
                  #   failure (0013); machine, group (0018); lmstudio (0019)
└── ui/           # step 7: launch, app, window, sidebar, tasks, i18n, texts, labels, theme,
                  #   icons (and icons/, Lucide's), parts, shown, settings, dialogs, sessions,
                  #   overview, findings, organize, autostart, quarantine, recovery, explain,
                  #   settings_page (0014); step 8: errors, selftest (0015); motion (0018);
                  #   brand (0019); manual (0021)
```

Directories are created only when their step starts.
