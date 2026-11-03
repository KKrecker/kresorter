# 0015. Packaging: a wheel and an sdist first, one version, the licences in every artifact

- Status: proposed
- Date: 2026-11-03
- Builds on: 0001 (items 1, 5), 0004, 0005, 0012, 0014 (items 8-10), the pre-step-8 audit
  (A4, A6, B1, B5, B6)
- Amends: 0014 item 9 (on Windows, the line a GUI script cannot write is shown in a message
  box)

## Context

Step 8 makes a release of what steps 1 to 7 built: something a user installs, with a version,
a licence, a changelog that says what it has, and screenshots in the README. The pre-step-8
audit lists what is missing: no licence text, no metadata, the version written twice and no
command that prints it (A4); a changelog that is the log of the development (A6); development
tools with lower bounds only (B5); nothing built or published (B6). The window has never
opened on Windows or macOS, where a GUI script has no standard error (B1).

What safeclean is decides what can be shipped:

- The core is pure Python with no dependency (0001 item 5) and the window is the extra `ui`
  (`PySide6-Essentials`, LGPLv3; 0014 item 8). One wheel, `py3-none-any`, and an sdist serve
  every system with Python 3.11 to 3.14; `pipx install "safeclean[ui]"` installs both commands
  in a virtual environment of their own, and pip installs Qt from its own wheels, with its
  own licences.
- The quarantine and organize act only where the open-file check can be trusted (0005, 0012):
  Linux today. On macOS and Windows they refuse, so there a release scans, analyzes, explains
  and lists autostart entries, and on Windows changes `HKCU` Run values (0011).
- A sandboxed package (Flatpak, Snap) shows the open-file check only the processes of its own
  sandbox: it would find every file closed. It is never shipped.
- A bundle that carries Python and Qt (PyInstaller, Briefcase, an MSI, a DMG) brings Qt's LGPL
  duties (its licence, its source, a way to replace its libraries), signing (SmartScreen,
  notarization) and a test on every system it targets. None of it can be checked before the
  window has run on those systems (B1), so bundles are a later decision, each after CI and a
  clean machine of its system pass.

So the first release, `0.1.0`, is a wheel and an sdist on PyPI. The owner's answers, and the
questions still open, are at the end.

Every numbered item below is a behaviour a test can show, and is cited by one (item 25). The
tests that build an artifact build it once per run, offline, into a temporary folder.

## The name

1. **Kresorter.** The project and its window are Kresorter: "Kre" for its author, KKrecker,
   and a sorter. The package is `kresorter`, the commands `kresorter` and `kresorter-ui`
   (`python -m kresorter`, `python -m kresorter.ui`), the data directory `kresorter` with its
   lock `kresorter.lock`, the variables `KRESORTER_OLLAMA_URL` and `KRESORTER_OLLAMA_MODEL`,
   and the window's title `Kresorter`. Until step 8 the project was called safeclean: this
   item is the only place in the repository that names it, and nothing looks for a data
   directory of that name, since no release had it.

## The version

2. **Written once.** `safeclean.__version__` is the version; `pyproject.toml` has
   `dynamic = ["version"]`, reads it from `src/safeclean/__init__.py` and has no version of
   its own. The first release is `0.1.0`.
3. **`safeclean --version`** (and `python -m safeclean --version`) prints `safeclean 0.1.0` on
   stdout and exits with 0; it reads no setting, opens no journal and creates no data
   directory.
4. **The window names it**: the Settings page shows `safeclean 0.1.0` under the data folder,
   in both languages.

## Licences and metadata

5. **The licence is in the repository and in every artifact.** `LICENSE` at the root is the
   MIT licence with "Copyright (c) 2026 KKrecker"; `pyproject.toml` declares
   `license = "MIT"` and `license-files = ["LICENSE", "src/safeclean/ui/icons/LICENSE"]`
   (PEP 639). The wheel's `.dist-info/licenses/` and the sdist have both files, and the
   README's License section names both: MIT for safeclean, ISC for Lucide's icons.
6. **Nothing of Qt is shipped**: neither artifact has a file of PySide6, shiboken6 or Qt.
7. **Metadata**: `authors` (the holder of item 5, with no e-mail address), `project.urls` (Homepage, Source, Issues,
   Changelog), `keywords`, and the classifiers Development Status :: 3 - Alpha, Environment ::
   Console, Environment :: X11 Applications :: Qt, Intended Audience :: End Users/Desktop,
   the three systems (POSIX :: Linux, Microsoft :: Windows, MacOS), Programming Language ::
   Python :: 3 :: Only, one per Python from 3.11 to 3.14 (as `requires-python` and CI's
   matrix), Topic :: System :: Filesystems, Topic :: Utilities and Typing :: Typed. No licence
   classifier: PEP 639 replaces it with the expression.

## The artifacts

8. **One wheel for every system**, `safeclean-0.1.0-py3-none-any.whl`: the package's modules,
   `py.typed`, the icons and their licence, and no test, document or other file; its entry
   points are those of 0014 item 8.
9. **The sdist makes the same wheel**: it has `src`, `tests`, `docs`, `README.md`,
   `CHANGELOG.md`, `LICENSE`, `pyproject.toml` and the `PKG-INFO` it is given, and nothing
   else; the wheel built from it has the same files as the wheel built from the repository.
10. **Installed from the wheel, offline**: in a new virtual environment,
   `pip install --no-index` of the wheel installs nothing else; `safeclean --version`,
   `safeclean scan --json` on a made-up tree and `safeclean-ui` without PySide6 (one line,
   exit 3) behave as from the source tree.
11. **Uninstalling keeps the user's data**: `pip uninstall` removes every file the wheel
    installed and nothing of the data directory, where the journal, the vault with the
    quarantined files, the autostart store and `settings.json` stay. The README's
    "Uninstalling" says so, names the data directory, says that quarantined files are still in
    it (`safeclean quarantine list`; restore or purge them first) and that removing the
    folder is the user's own step.

## The changelog

12. **The changelog says what a release has.** `CHANGELOG.md` has `## [Unreleased]` above
    `## [0.1.0] - YYYY-MM-DD`, whose entries, in Keep a Changelog's categories, are what the
    release does: one per command and one per page of the window, not the development's log,
    which stays in git and in the roadmap. The latest version in it is `__version__`, and each
    change after it adds its entry under `[Unreleased]`.

## Development tools

13. **Pinned.** The extra `dev` pins every tool to one version (`ruff`, `mypy`, `pytest`,
    `pytest-cov`, `pytest-qt`, `build`, `hatchling`) and `PySide6-Essentials` to the one CI
    tests; the extra `ui` keeps its range, `>=6.8,<7`. A tool changes in a commit of its own.
    `[build-system]` requires a `hatchling` that has PEP 639 (`>=1.27,<2`).

## CI and the release

14. **Three systems.** The checks run on `ubuntu-latest`, `windows-latest` and `macos-latest`
    for every Python of the matrix (pre-step-5 audit B11); Qt's system libraries are installed
    on Linux only, and the window's tests run offscreen on each.
15. **The artifacts are built once**, in a job after the checks: the sdist, then the wheel
    from the sdist, items 8 to 10 checked on them, both kept as the run's artifacts.
16. **The installed wheel runs on each system**: a job per system installs the artifact of
    item 15 in a new virtual environment with the extra `ui`, runs `safeclean --version` and
    `safeclean scan` on a made-up tree, and opens the window offscreen, shows each page and
    closes it, exit 0.
17. **A tag publishes, nothing else.** A tag `vX.Y.Z` publishes the artifacts of item 15 to
    PyPI by trusted publishing (OpenID Connect, the environment `pypi`): no token in the
    repository or its secrets. The tag must be `__version__` and the latest version of the
    changelog; otherwise the job fails before anything is published.

## Windows: a GUI script has no console (B1)

18. **The line becomes a message box.** On Windows, when `safeclean-ui` has no standard error
    and cannot open the window (0014 item 9), its line is shown in a system message box
    (`MessageBoxW` through `ctypes`, which needs no Qt). Elsewhere nothing is shown.
19. **An uncaught error is a dialog.** An exception that reaches Qt's event loop is shown in a
    dialog: its type and message, and the traceback in a read-only plain-text box that can be
    copied; the window stays open, and nothing is sent anywhere. With a standard error, the
    traceback is written there too.

## Screenshots

20. **Made by a script, not drawn.** `tests/support/screenshots.py` opens the window
    offscreen, 1280 x 800, on a made-up tree in a temporary home (nothing of the user's), and
    writes `docs/screenshots/<screen>.png` for the prototype's six screens: Overview,
    Findings, the confirmation, Organize, Autostart, and Findings in the dark, in English.
21. **The README shows them**: each image the README shows exists in `docs/screenshots/`, is a
    PNG of 1280 x 800, and every image there is shown. A test runs the script for one screen
    into a temporary folder, so it cannot fall behind the window.

## The release record

22. **A clean machine of each system before the tag.** `docs/releases/<version>.md` records,
    for each system of the classifiers, a run on a new virtual machine: the system and its
    version, the Python, the install command, and what was done and seen (the window opened
    on a screen, a scan, each page, the refusals of the quarantine and organize on macOS and
    Windows); the job of item 17 fails without it.
23. **The README installs with pipx**: its first install commands are
    `pipx install safeclean` and `pipx install "safeclean[ui]"`, then pip in a virtual
    environment; it says where the quarantine and organize refuse.
24. **The roadmap records step 8**: a section `Step 8: done (packaging)` and what it carries
    after it.

## The meta-test

25. **Every item of this decision is cited by a test** as `[0015.N]`. A meta-test fails on an
    item no test cites, on a citation of an item that does not exist, and on an item still
    listed as pending although a test cites it; the pending list starts with every item and is
    empty after the last commit of the step 8 plan. The meta-test checks the rules of
    `tests/support/decisions.py` on made-up items and citations, and that check cites this
    item.

## Step 8 plan

Each line is one commit or one test/fix pair (red, then green). The items in brackets leave
the pending list in that commit, and no earlier test cites them.

1. The meta-test, every other item pending [25].
2. The name: Kresorter everywhere [1].
3. The tools pinned, `build` and `hatchling` with them [13].
4. The version: one place, `--version`, Settings [2-4].
5. The licence and the metadata [5-7].
6. The artifacts: the wheel, the sdist, installed offline, uninstalled [8-11].
7. Windows: the message box; an uncaught error in a dialog [18, 19].
8. The screenshots and the README's images [20, 21].
9. CI: three systems, the artifacts, the installed wheel, publishing from a tag [14-17].
10. The changelog of 0.1.0, the README (pipx, uninstalling), the roadmap [12, 23, 24].
11. The release record, after the runs on clean machines [22]; then the tag, by the owner.

## Accepted limitations

- **No installer or bundle in 0.1.0**: Python 3.11 or newer and pipx (or pip) are needed.
- **macOS and Windows get the reports**: the quarantine and organize refuse there until their
  open-file backends exist; autostart changes only `HKCU` Run values on Windows.
- **Nothing is signed**: a wheel has nothing to sign; PyPI's trusted publishing ties each file
  to the workflow that built it.
- **No Flatpak, no Snap**, for the reason in the context.

## The owner's answers

- The licence's holder and the author: KKrecker, with no e-mail address (items 5, 7).
- The repository: public, `github.com/KKrecker/kresorter`, its history written by KKrecker.
- The clean machines of item 22: the owner runs them.
- The screenshots: the English window only (item 20).
- The first version: `0.1.0`, Alpha, with a changelog for its users (item 12).

## Questions for the owner

1. Windows: an installer, a portable `Kresorter.exe`, or both; whether the Windows open-file
   backend comes before them (without it the quarantine and organize refuse there); and
   whether the files are signed.
2. Whether PyPI stays, for Linux and the command line.
