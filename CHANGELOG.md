# Changelog

What each release of Kresorter brings to its users. The format is
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). How it was built, step by step, is
in git's history and in the [roadmap](docs/roadmap.md).

## [Unreleased]

## [0.1.0] - 2026-11-05

The first release, an alpha: the console commands and the window, on Windows and Linux.

### Added

- `kresorter scan [paths] [--json] [--no-hash]`: junk candidates (caches, temporary files,
  thumbnails, crash dumps, the system's metadata files), duplicate groups and everything it
  skipped, with the reason; the safe zones `~/.cache` and `~/Downloads` when no folder is
  named. It only reads.
- `kresorter analyze [paths] [--json] [--large MIB] [--older-than DAYS] [--explain]`: a safety
  level for each finding, `safe`, `likely_safe` or `review`, with every reason; a cache is
  `likely_safe` and a browser's cache `review`, never proposed; the copy of a duplicate group
  that stays is chosen for you and never proposed, and large and old files are listed for
  review only. It only reads.
- `kresorter quarantine add|list|restore|purge`: files moved aside into a private vault in the
  data directory, each checked again right before it moves (the policy, the disk, open files),
  or the findings of an analysis with `--from-analysis --level safe|likely_safe`; `restore`
  puts them back and never overwrites; `purge` shows what it would delete and deletes the
  vault's copies only with `--yes`. On Linux and Windows; refused on macOS, which has no
  open-file check yet.
- `kresorter organize move|list|undo`: the regular files directly in a folder sorted into
  `Images`, `Videos`, `Audio`, `Documents`, `Archives` and `Installers` as one batch, which
  `undo` moves back; the plan first, the move only with `--yes`, and every file that stays
  listed with its reason. A folder whose files break when moved is refused as a whole (the home
  directory, a project, a game library, a cache, and on Windows a folder a sync client keeps).
  On Linux and Windows; refused on macOS.
- `kresorter autostart list|disable|enable|recover`: the programs that start on their own, by
  source (XDG entries and systemd user units on Linux; Run keys, startup folders and, with
  `--include-machine`, services and scheduled tasks on Windows; launchd on macOS), each with an
  id; `disable` and `enable` change one XDG entry or `HKCU` Run value by that id, and nothing
  is deleted.
- `kresorter recover`: the work an interruption left (a quarantine, an organize batch, an
  autostart change) closed by what is on the disk or in the registry, never redone or undone;
  every command that acts does it for its own work first.
- `kresorter llm status`: whether the local AI, Ollama or LM Studio, can give the advisory
  explanations of `analyze --explain` and of the window's Explain, and the steps left to set it
  up; it is asked on loopback only, and what it says is only ever shown.
- LM Studio as well as Ollama: `KRESORTER_LLM_SERVER` set to `lmstudio`, with
  `KRESORTER_LMSTUDIO_URL` (by default `http://127.0.0.1:1234`) and `KRESORTER_LMSTUDIO_MODEL`
  (by default the first model it lists that is not an embedding model), or the server chosen
  in the window. It is asked for its models and for an answer only, never to download, load or
  unload a model, and it is sent the same facts as Ollama.
- The AI explanations in the window's language, English or Russian, and in English on the
  console; a reasoning model's thinking is left out of the answer.
- `kresorter --version`.
- One journal and one lock for everything that acts: each action is journaled before the disk
  is touched, shows what it will do and acts only once confirmed (`--yes`, or the window's
  dialog), and one runs at a time. Nothing is deleted but by `quarantine purge` or the window's
  Delete permanently.
- Never findings: the system's and the programs' folders, the profile's private ones
  (`~/.ssh`, `~/.gnupg`, `AppData\Roaming`), open files, Kresorter's data directory and the
  folder it runs from; links are never followed.
- The window, `kresorter-ui` (or `python -m kresorter.ui`) with the extra `ui`: a sidebar of
  six pages, in English or Russian, light or dark as the system is or as chosen, running what
  the commands run on the same journal and lock; every action opens a dialog first, with
  Cancel as its default button. A name is shown as it is written, never as formatting. Its
  icon, Kresorter's mark, is in the title bar, on the taskbar and in every dialog.
- The **Overview** page: the folders to scan, a safe zone left out and put back as you choose,
  and Scan now, which only reads and shows its progress; a card per safety level with its
  files, size and strongest reasons, and a card each for Quarantine, Organize, Autostart and
  Local AI, the server and the model in use and whether the last Check found it.
- The **Findings** page: the findings grouped by their strongest reason, with a chip per level,
  a search and the detail of the file chosen; only the Safe ones are selected at first, and
  Move to quarantine moves the selection.
- The **Organize** page: a folder's plan as a card per category and the files that stay, with
  their reasons; Group by meaning (local AI) groups the files by what their names say, sending
  the local model their names only, and By kind goes back; Sort moves the plan shown as one
  batch, and the recent batches can be undone.
- The **Autostart** page: the entries by source, each with its location, its scope and a
  switch that disables or enables it where it can change, and a lock where it cannot.
- The **Quarantine** page: the quarantined files, with Select all and Clear selection, Restore,
  and Delete permanently.
- The **Settings** page: the language, applied at once with Restart now; Appearance, System,
  Light or Dark; on Windows the machine-wide autostart entries; the local AI with its Server,
  Ollama or LM Studio, its Check, the model chosen among those the server has and the one
  recommended for the computer; the data folder, the version and the licence: Kresorter's, the
  MIT licence, and the Windows build's Qt and PySide6, under the LGPL-3.0.
- `kresorter-ui --self-test REPORT`: opens the window, shows each page, closes it and writes a
  line per page to `REPORT`, changing nothing; on a failure, the error and exit code 1.
- For Windows, `Kresorter-0.1.0-setup.exe`, for the current user with no administrator rights,
  and `Kresorter-0.1.0-portable.zip`, which runs from any folder: the window, with its
  licences and Qt's beside it; the installer shows the licence before it installs. Neither is
  signed, so SmartScreen warns before the first run.
- The GitHub release `Kresorter 0.1.0`: `Kresorter-0.1.0-setup.exe`,
  `Kresorter-0.1.0-portable.zip`, `kresorter-0.1.0-py3-none-any.whl`, one wheel for every
  system and Python 3.11 to 3.14, the sdist `kresorter-0.1.0.tar.gz` and `SHA256SUMS.txt`, to
  check each file against. `pipx install "kresorter[ui]"` installs the window and the commands,
  `pipx install kresorter` the commands only, from PyPI, or from the wheel's path when PyPI
  does not have it.
- The README in English and in Russian, `README.ru.md`, each with a switch to the other.
- Uninstalling leaves the data directory, with the files still in the quarantine; the README
  says how to restore or purge them first.
