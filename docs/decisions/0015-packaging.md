# 0015. Packaging: a Windows installer and a portable zip, a wheel on PyPI, one version, the licences in every artifact

- Status: accepted
- Date: 2026-11-03
- Builds on: 0001 (items 1, 5), 0004, 0005, 0012, 0014 (items 8-10), 0016, 0017, the
  pre-step-8 audit (A4, A6, B1, B5, B6)
- Amends: 0014 item 9 (on Windows, the line a GUI script cannot write is shown in a message
  box)

## Context

Step 8 makes a release of what steps 1 to 7 built: something a user installs, with a version,
a licence, a changelog that says what it has, and screenshots in the README. The pre-step-8
audit lists what is missing: no licence text, no metadata, the version written twice and no
command that prints it (A4); a changelog that is the log of the development (A6); development
tools with lower bounds only (B5); nothing built or published (B6). The window has never
opened on Windows, where a GUI script has no standard error (B1).

The owner wants a Windows application first: an installer and a portable zip. What Kresorter
is decides how:

- The quarantine acts only where the open-file check can be trusted (0004, 0005): Linux today.
  Decision 0016 gives Windows its check first, so the Windows application can quarantine,
  restore and purge, not only report. Decision 0017 then lifts organize's refusal there (0012
  item 37): renames tried again, a path limit, synced folders refused.
- The window needs Python and Qt. A one-folder build (PyInstaller) carries both, with Qt's
  libraries as files of their own, so its LGPL duties hold: Qt's licence, where its source is,
  and a way to replace its libraries. A one-file executable unpacks itself at every start,
  starts slower and hides the libraries in itself; the portable zip is the folder instead.
- A build for Windows is made on Windows: CI's `windows-latest` builds the folder, the zip and
  the installer (Inno Setup); this machine runs Linux and can check only their scripts.
- The core is pure Python with no dependency (0001 item 5) and the window is the extra `ui`
  (`PySide6-Essentials`; 0014 item 8). One wheel, `py3-none-any`, and an sdist on PyPI are the
  second channel, for Linux and the command line: `pipx install "kresorter[ui]"` installs both
  commands in a virtual environment of their own.
- A sandboxed package (Flatpak, Snap) shows the open-file check only the processes of its own
  sandbox: it would find every file closed. It is never shipped.
- macOS comes later: it has no open-file check, no build and no machine to try it on.
- Nothing is signed in 0.1.0: Windows warns before an unsigned installer runs (SmartScreen),
  and the README says how to go on and how to check the files' SHA-256.

Every numbered item below is a behaviour a test can show, and is cited by one (item 31). The
tests that build an artifact build it once per run, offline, into a temporary folder; what only
Windows can build is checked by CI there (items 21, 22).

## The name

1. **Kresorter.** The project and its window are Kresorter: "Kre" for its author, KKrecker,
   and a sorter. The package is `kresorter`, the commands `kresorter` and `kresorter-ui`
   (`python -m kresorter`, `python -m kresorter.ui`), the data directory `kresorter` with its
   lock `kresorter.lock`, the variables `KRESORTER_OLLAMA_URL` and `KRESORTER_OLLAMA_MODEL`,
   and the window's title `Kresorter`. Until step 8 the project was called safeclean: this
   item is the only place in the repository that names it, and nothing looks for a data
   directory of that name, since no release had it.

## The version

2. **Written once.** `kresorter.__version__` is the version; `pyproject.toml` has
   `dynamic = ["version"]`, reads it from `src/kresorter/__init__.py` and has no version of
   its own. The first release is `0.1.0`.
3. **`kresorter --version`** (and `python -m kresorter --version`) prints `kresorter 0.1.0` on
   stdout and exits with 0; it reads no setting, opens no journal and creates no data
   directory.
4. **The window names it**: the Settings page shows `Kresorter 0.1.0` under the data folder,
   in both languages.

## Licences and metadata

5. **The licence is in the repository and in every artifact.** `LICENSE` at the root is the
   MIT licence with "Copyright (c) 2026 KKrecker"; `pyproject.toml` declares
   `license = "MIT"` and `license-files = ["LICENSE", "src/kresorter/ui/icons/LICENSE"]`
   (PEP 639). The wheel's `.dist-info/licenses/` and the sdist have both files, and the
   README's License section names both: MIT for Kresorter, ISC for Lucide's icons.
6. **The wheel and the sdist carry nothing of Qt**: no file of PySide6, shiboken6 or Qt; pip
   installs them from their own wheels, with their own licences.
7. **Metadata**: `authors` (KKrecker, with no e-mail address), `project.urls` (Homepage,
   Source, Issues, Changelog, all under `https://github.com/KKrecker/kresorter`), `keywords`,
   and the classifiers Development Status :: 3 - Alpha, Environment :: Console, Environment ::
   Win32 (MS Windows), Environment :: X11 Applications :: Qt, Intended Audience :: End
   Users/Desktop, Operating System :: Microsoft :: Windows, Operating System :: POSIX ::
   Linux, Programming Language :: Python :: 3 :: Only, one per Python from 3.11 to 3.14 (as
   `requires-python` and CI's matrix), Topic :: System :: Filesystems, Topic :: Utilities and
   Typing :: Typed. No licence classifier (PEP 639 replaces it with the expression), and no
   macOS.

## The wheel and the sdist

8. **One wheel for every system**, `kresorter-0.1.0-py3-none-any.whl`: the package's modules,
   `py.typed`, the icons and their licence, and no test, document or other file; its entry
   points are those of 0014 item 8.
9. **The sdist makes the same wheel**: it has `src`, `tests`, `docs`, `README.md`,
   `CHANGELOG.md`, `LICENSE`, `pyproject.toml`, the `PKG-INFO` it is given and the
   `.gitignore` hatchling adds to every sdist (a wheel made from the sdist leaves out what the
   repository's leaves out), and nothing else; the wheel built from it has the same files as
   the wheel built from the repository.
10. **Installed from the wheel, offline**: in a new virtual environment,
    `pip install --no-index` of the wheel installs nothing else; `kresorter --version`,
    `kresorter scan --json` on a made-up tree and `kresorter-ui` without PySide6 (one line,
    exit 3) behave as from the source tree.
11. **Uninstalling keeps the user's data**: `pip uninstall` removes every file the wheel
    installed and nothing of the data directory, where the journal, the vault with the
    quarantined files, the autostart store and `settings.json` stay.

## The Windows application

12. **One folder.** `packaging/windows/kresorter.spec` makes, with PyInstaller and the Python
    3.13 of CI's Windows job, from the wheel of item 8 and the extra `ui`, a folder
    `Kresorter` with `Kresorter.exe`: the window, with no console. The executable has the
    sidebar's mark as its icon (`kresorter.ico`, made from the SVG by a script) and a version
    resource: product Kresorter, the version of item 2, KKrecker, "Safe file cleanup".
13. **The licences travel with it**: the folder has `LICENSE`, `THIRD-PARTY-NOTICES.txt`
    (Python, PySide6, shiboken6 and Qt under LGPLv3 with where their source is, Lucide under
    ISC, PyInstaller's bootloader under its GPL with the exception that allows this), the
    licence texts the PySide6 wheel ships, and Qt's libraries as files of their own, which a
    user can replace.
14. **The portable zip**, `Kresorter-0.1.0-portable.zip`, is that folder: it runs from any
    folder, writes nothing beside itself, and keeps its data where the installed one does
    (`%LOCALAPPDATA%\kresorter`).
15. **The installer**, `Kresorter-0.1.0-setup.exe`, from `packaging/windows/kresorter.iss`
    (Inno Setup): for the current user, with no administrator rights, into
    `%LOCALAPPDATA%\Programs\Kresorter`; a Start menu shortcut, a desktop one if asked; listed
    in Windows' Apps with its version and KKrecker. Its uninstaller removes what it installed
    and never the data directory: the script names no `[UninstallDelete]` and no path of the
    data directory, and the README's "Uninstalling" says that the quarantined files are still
    there (`kresorter quarantine list`, or the Quarantine page: restore or purge them first)
    and that removing the folder is the user's own step.
16. **Its own files are never findings**: the policy blocks the folder Kresorter runs from,
    like the data directory: the package's folder, and when frozen the folder of the
    executable, so a scan of `%LOCALAPPDATA%` or of a virtual environment never proposes
    Kresorter itself.
17. **A self-test**: `kresorter-ui --self-test REPORT` opens the window, shows each page,
    closes it and writes one line per page to `REPORT`, then exits with 0, changing nothing;
    a failure is its traceback in `REPORT` and exit 1. CI runs it on the installed wheel and
    on the Windows application, offscreen; the owner can run it on a clean machine.

## The changelog

18. **The changelog says what a release has.** `CHANGELOG.md` has `## [Unreleased]` above
    `## [0.1.0] - YYYY-MM-DD`, whose entries, in Keep a Changelog's categories, are what the
    release does: one per command and one per page of the window, not the development's log,
    which stays in git and in the roadmap. The latest version in it is `__version__`, and each
    change after it adds its entry under `[Unreleased]`.

## Development tools

19. **Pinned.** The extra `dev` pins every tool to one version (`ruff`, `mypy`, `pytest`,
    `pytest-cov`, `pytest-qt`, `build`, `hatchling`) and `PySide6-Essentials` to the one CI
    tests; the extra `ui` keeps its range, `>=6.8,<7`. PyInstaller is pinned in
    `packaging/windows/requirements.txt`, Inno Setup's version in the workflow. A tool changes
    in a commit of its own. `[build-system]` requires a `hatchling` that has PEP 639
    (`>=1.27,<2`).

## CI and the release

20. **Two systems.** The checks run on `ubuntu-latest` for every Python of the matrix and on
    `windows-latest` for the oldest and the newest (3.11, 3.14) while the repository is
    private, for every Python once it is public (pre-step-5 audit B11); Qt's system libraries
    are installed on Linux only, and the window's tests run offscreen on both.
21. **The artifacts are built once**, in jobs after the checks: on Linux the sdist, then the
    wheel from the sdist, items 8 to 10 checked on them; on Windows, from that wheel, the
    folder, the zip and the installer of items 12 to 15. All are kept as the run's artifacts.
22. **What is built is run**: on each system the wheel in a new virtual environment with the
    extra `ui`, `kresorter --version` and the self-test of item 17; on Windows the installer
    run silently for the current user, the self-test of the installed `Kresorter.exe` and of
    the unzipped portable one, then the silent uninstall, after which the installed folder is
    gone and the data directory is still there.
23. **A tag publishes, nothing else.** A tag `vX.Y.Z` publishes the wheel and the sdist to
    PyPI by trusted publishing (OpenID Connect, the environment `pypi`: no token in the
    repository or its secrets) and makes a GitHub release with the installer, the portable
    zip, the wheel, the sdist and `SHA256SUMS.txt`. The tag must be `__version__` and the
    latest version of the changelog; otherwise the job fails before anything is published.

## Windows: a GUI program has no console (B1)

24. **The line becomes a message box.** On Windows, when `kresorter-ui` or `Kresorter.exe`
    has no standard error and cannot open the window (0014 item 9), its line is shown in a
    system message box (`MessageBoxW` through `ctypes`, which needs no Qt). Elsewhere nothing
    is shown.
25. **An uncaught error is a dialog.** An exception that reaches Qt's event loop is shown in a
    dialog: its type and message, and the traceback in a read-only plain-text box that can be
    copied; the window stays open, and nothing is sent anywhere. With a standard error, the
    traceback is written there too.

## Screenshots

26. **Made by a script, not drawn.** `tests/support/screenshots.py` opens the window
    offscreen, 1280 x 800, on a made-up tree in a temporary home (nothing of the user's), and
    writes `docs/screenshots/<screen>.png` for the prototype's six screens: Overview,
    Findings, the confirmation, Organize, Autostart, and Findings in the dark, in English.
27. **The README shows them**: each image the README shows exists in `docs/screenshots/`, is a
    PNG of 1280 x 800, and every image there is shown. A test runs the script for one screen
    into a temporary folder, so it cannot fall behind the window.

## The release record and the documents

28. **Clean machines before the tag.** `docs/releases/<version>.md` records a run on each of
    Windows 10 and Windows 11 (the installer and the portable zip) and on an Ubuntu LTS
    (pipx): the system and its version, how it was installed, and what was done and seen (the
    window on a screen, a scan, a file quarantined and restored, each page, a folder sorted
    and its batch undone, the uninstall); the job of item 23 fails without it.
29. **The README installs Kresorter**: Windows first (the installer or the portable zip from
    the releases, how to pass SmartScreen, how to check `SHA256SUMS.txt`), then Linux with
    `pipx install "kresorter[ui]"` and `pipx install kresorter`; it says what each system can
    do (organize on Linux and Windows, not on macOS) and how to uninstall.
30. **The roadmap records step 8**: a section `Step 8: done (packaging)` and what it carries
    after it.

## The meta-test

31. **Every item of this decision is cited by a test** as `[0015.N]`. A meta-test fails on an
    item no test cites, on a citation of an item that does not exist, and on an item still
    listed as pending although a test cites it; the pending list starts with every item and is
    empty after the last commit of the step 8 plan. The meta-test checks the rules of
    `tests/support/decisions.py` on made-up items and citations, and that check cites this
    item.

## Step 8 plan

Each line is one commit or one test/fix pair (red, then green). The items in brackets leave
the pending list in that commit, and no earlier test cites them.

1. The meta-test, every other item pending [31]. Done.
2. The name: Kresorter everywhere [1]. Done.
3. The tools pinned, `build` and `hatchling` with them [19].
4. The version: one place, `--version`, Settings [2-4].
5. The licence and the metadata [5-7].
6. The wheel and the sdist, installed offline, uninstalled [8-11].
7. Windows without a console: the message box; an uncaught error in a dialog [24, 25].
8. The self-test; Kresorter's own files never findings [16, 17].
9. Decision 0016, by its own plan: the Windows open-file check, the quarantine on Windows.
10. Decision 0017, by its own plan: organize on Windows.
11. CI on two systems, and what fails on Windows fixed, each with its test [20].
12. The Windows application: the folder, its licences, the zip, the installer [12-15].
13. CI: the artifacts, what is built is run, publishing from a tag [21-23].
14. The screenshots and the README's images [26, 27].
15. The changelog of 0.1.0, the README, the roadmap [18, 29, 30].
16. The release record, after the owner's runs on clean machines [28]; then the tag, by the
    owner, once the repository is public.

## Accepted limitations

- **Unsigned**: SmartScreen warns before the installer and `Kresorter.exe` run; signing (a
  certificate, or SignPath for open-source projects) is a later decision.
- **The Windows application is the window**: the commands come with `pipx install kresorter`.
- **Organize on Windows leaves synced folders alone** (0017): Desktop and Documents moved into
  OneDrive are not sorted.
- **No macOS build**, and macOS is not claimed by the metadata.
- **No Flatpak, no Snap**, for the reason in the context.

## The owner's answers

- The licence's holder and the author: KKrecker, with no e-mail address (items 5, 7).
- The repository: `github.com/KKrecker/kresorter`, its history written by KKrecker; private
  first, public before the first tag (items 20, 23).
- Windows first: an installer and a portable zip, after the Windows open-file check (0016);
  PyPI stays, as the second channel; nothing signed in 0.1.0; macOS later.
- The clean machines of item 28: the owner runs them.
- The screenshots: the English window only (item 26).
- The first version: `0.1.0`, Alpha, with a changelog for its users (item 18).
- Accepted (2026-11-03), with organize on Windows in 0.1.0 (0017).
