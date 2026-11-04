# Changelog

What each release of Kresorter brings to its users. The format is
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). How it was built, step by step, is
in git's history and in the [roadmap](docs/roadmap.md).

## [Unreleased]

## [0.1.0] - 2026-11-03

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
- `kresorter llm status`: whether a local Ollama can give the advisory explanations of
  `analyze --explain` and of the window's Explain; it is asked on loopback only, and what it
  says is only ever shown.
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
  Cancel as its default button. A name is shown as it is written, never as formatting.
- The **Overview** page: the folders to scan, a safe zone left out and put back as you choose,
  and Scan now, which only reads and shows its progress; a card per safety level with its
  files, size and strongest reasons, and a card each for Quarantine, Organize, Autostart and
  Local AI, the model in use and whether the last Check found it.
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
  Light or Dark; on Windows the machine-wide autostart entries; the local AI with its Check,
  the model chosen among those Ollama has and the one recommended for the computer; the data
  folder and the version.
- `kresorter-ui --self-test REPORT`: opens the window, shows each page, closes it and writes a
  line per page to `REPORT`, changing nothing; on a failure, the error and exit code 1.
- For Windows, `Kresorter-0.1.0-setup.exe`, for the current user with no administrator rights,
  and `Kresorter-0.1.0-portable.zip`, which runs from any folder: the window, with its
  licences and Qt's beside it. Neither is signed, so SmartScreen warns before the first run.
- On PyPI, one wheel for every system and Python 3.11 to 3.14: `pipx install "kresorter[ui]"`
  for the window and the commands, `pipx install kresorter` for the commands only.
- Uninstalling leaves the data directory, with the files still in the quarantine; the README
  says how to restore or purge them first.
