# 0011. Autostart: read first, disable reversibly, never delete

- Status: accepted
- Date: 2026-11-01
- Builds on: 0001, 0004 (vault), 0006, 0008 (single deletion point)

## Principles

1. **Listing is read-only.** Readers parse files and registry values; they never write, and an
   entry they cannot parse is reported as skipped with a reason, never as an error that stops
   the listing.
2. **Disabling is reversible and never deletes.** No reader or action removes an autostart
   entry. Where a file has to change or go away, its original bytes go through the vault
   first, exactly like any quarantined file, and come back on enable.
3. **Act only on what was shown.** Every item carries a `digest` of the raw entry as it was read
   (file bytes; for a registry value its name, type and data in a fixed encoding). Right before
   disabling or enabling, the entry is read again; a different digest is a refusal, not a
   retry.
4. **Each source is explicit.** Sources: XDG autostart, systemd user units, Run/RunOnce keys,
   startup folders, services, scheduled tasks, LaunchAgents. Scope says where the entry
   *lives*: `user` (the user's own files or `HKCU`) or `system` (`/etc`, `/Library`, `HKLM`,
   services).
5. **The machine scope of the registry is opt-in.** `HKLM` is read only with
   `--include-machine`; nothing remembers the consent (that belongs to the settings decision
   in step 7).

## XDG overrides

6. **A user entry replaces the system entry of the same file name** (`$XDG_CONFIG_HOME/autostart`
   over every directory in `$XDG_CONFIG_DIRS`, first one wins), as the desktop does. The listing
   shows **one item per name with its effective state**: `location` is the file that is in
   effect, `shadows` the system file it replaces. A system entry hidden by a user stub
   (`Hidden=true`) is therefore listed as disabled, with the stub as `location` and the system
   file as `shadows`. `shadows` exists only for XDG items whose `location` is in the user scope.
7. **Effective state**: `Hidden=true` disables; `X-GNOME-Autostart-enabled=false` disables;
   `OnlyShowIn`/`NotShowIn` are reported as they are, not evaluated against the current
   desktop.

## What can be disabled in step 4

8. **XDG autostart and `HKCU` Run only.** Everything else is listed, read-only:
   - XDG, the user's own entry: the original goes to the vault, then a copy with `Hidden=true`
     is written in its place; enable puts the original back.
   - XDG, a system entry: a user stub with `Hidden=true` is created; `/etc` is never written.
     Enable sends the stub through the quarantine; the system file was never touched.
   - `HKCU` Run: the `StartupApproved\Run` flag, as the Task Manager does; the `Run` value
     itself is never touched. `StartupApproved` is also the source of the listed state.
9. **Read-only in step 4, each needing its own risk analysis:** systemd user units, services,
   scheduled tasks, LaunchAgents (they change boot or session behaviour); `RunOnce` (no
   `StartupApproved` state exists for it); startup folders; `HKLM` Run (writing it needs
   elevation).
10. **Every change is journaled before it is made** (schema v3, `autostart_changes`): source,
    location, value before and after, digest; interrupted changes are reconciled by
    `recover()` like quarantine operations.

## Testing

11. Linux readers are tested on real temporary trees. Windows and macOS readers are tested on
    a fake registry (a `Registry` protocol) and on sample files; the thin adapter to `winreg`
    imports it lazily and is tested with a stand-in module, like `MsvcrtBackend` (0009).

## Addendum (step 4, commit 3): reading XDG entries

12. **An unknown effective state means the entry is not shown.** A user file that cannot be
    read still replaces the system entry of the same name, as it does for the desktop; since
    its effective state is unknown, the listing shows neither: the user file is skipped with
    its reason and the system entry is not listed as enabled. The same holds for a `Hidden=true`
    stub over a broken system entry, and for a stub that hides no entry at all.
13. **A `Hidden=true` stub shows the command it blocks.** Its `command` comes from the system
    file it hides (`shadows`), its `location` and `digest` from the stub itself, so the user
    sees what is being kept from starting and where that decision lives.
14. **Parsing is strict and bounded.** `[Desktop Entry]` must be the first group; `Type` must
    be `Application` and `Exec` non-empty (a `Hidden=true` user stub needs neither); a malformed
    line, a duplicate key or a non-boolean `Hidden`/`X-GNOME-Autostart-enabled` is a skip.
    Only regular files of at most 64 KiB are opened, so a FIFO never blocks the listing.
    `name` is the file name without `.desktop`, the key of the override; `Exec` is kept as is.

## Addendum (step 4, commit 4): reading systemd user units

15. **One item per link** in `$XDG_CONFIG_HOME/systemd/user/<target>.wants/`: a unit enabled for
    two targets is two items, each its own reason to start. `location` is the link, the target
    is the note `WantedBy=<target>`, `command` is the `ExecStart` of the unit file the link
    leads to, as written (prefixes and specifiers kept; several joined with `"; "`; an empty
    `ExecStart=` resets the list; `\` continues a line).
16. **The digest covers the link target, then `\0`, then the unit file bytes**, so pointing the
    link elsewhere changes it even when the content is the same.
17. **A masked unit** (`<unit>` in the same directory linked to `/dev/null`) is listed as
    disabled with the note `masked`: it is the real systemd state.
18. **A unit that is not a service** (`.timer`, `.socket`, `.path`, ...) is listed, not skipped:
    a timer is a legitimate way to start something. Its `command` is the path of its unit file
    and it carries the note `not a service: <type>`.
19. **Accepted limitations** (to revisit after the first live run on Linux, each with its own
    decision):
    - drop-ins (`<unit>.d/*.conf`) are not read, so an overridden `ExecStart` is shown as in
      the main unit file;
    - `<target>.requires/` is not read;
    - units enabled for all users (`/etc/systemd/user`) are not read.

## Addendum (step 4, commit 5): Run and RunOnce values

20. **Where Run values are read.** `HKCU` `Run` and `RunOnce` always; with `--include-machine`
    also `HKLM` `Run`/`RunOnce` and, read apart, the 32-bit view of `HKLM`
    (`Software\WOW6432Node\...\Run`/`RunOnce`) with its own flags in
    `Explorer\StartupApproved\Run32`. The 32-bit view is not a separate `Source` (the
    mechanism is the same Run); it differs by `location` and the note `32-bit view`, and the
    flags of one view never apply to the other. `HKCU` has no 32-bit view of `Run`. Without
    consent `HKLM` is not even read. Order: HKCU Run, HKCU RunOnce, HKLM Run, HKLM RunOnce,
    HKLM Run (32-bit), HKLM RunOnce (32-bit); by value name, ignoring case, within a key.
21. **The state of a Run value is its `StartupApproved` flag** of the same hive and view,
    matched by name ignoring case, as the Task Manager does: no flag is enabled; a binary flag
    starting with `0x02`/`0x06` is enabled, `0x03`/`0x07` disabled (with the note naming the
    flag key). Any other flag (another first byte, empty, not binary) is an unknown state and
    the value is skipped (item 12). A flag key that cannot be read makes the state of every
    Run value of that view unknown: one skip for the flag key, no items. A flag without a Run
    value is not an item.
22. **RunOnce values have no flag**; they are listed as they are with the note
    `runs once at the next logon`. A value that is not `REG_SZ`/`REG_EXPAND_SZ`, or is empty,
    is skipped; `REG_EXPAND_SZ` is kept unexpanded; the default value is named `(Default)`.
23. **The digest of a Run value covers the value and its flag** (name, type and data of each,
    every field length-prefixed, a missing flag included), so a changed flag counts as a
    changed entry.

## Addendum (step 4, commit 6): the `winreg` adapter

24. **`WinRegistry` opens every key read-only in the 64-bit view**
    (`KEY_READ | KEY_WOW64_64KEY`), so `WOW6432Node` paths are read where they are written and
    nothing is redirected behind our back. A missing key reads as `None`; any other failure,
    opening or enumerating, is a `RegistryError` with the reason; the key is always closed.
25. **Only `ERROR_NO_MORE_ITEMS` (259) ends an enumeration.** Any other error while enumerating
    (for example `ERROR_MORE_DATA`) is a failure of the whole key, never a silently shorter list.
26. `winreg` is imported on first use, like `msvcrt` (0009), and tested with a stand-in module.
    Choosing the registry per platform belongs to the `safeclean autostart list` commit.

## Addendum (step 4, commit 7): startup folders

27. **Where startup folders are read.** The user's
    (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`) always; the common one
    (`%ProgramData%\...\Programs\StartUp`) only with `--include-machine`, because its state
    lives in `HKLM` (item 5). A variable that is unset or not absolute means no folder. Order:
    the user folder, then the common one; by file name, ignoring case, within a folder.
28. **One item per file; the command is the file itself**, as Explorer opens it. `desktop.ini`
    is the folder's own settings and is not an entry. A sub-folder, a file larger than
    `MAX_ENTRY_BYTES` or one that cannot be read is skipped with a reason. A folder that does
    not exist is empty; one that exists but cannot be listed is a skip with the reason.
29. **Shortcut (`.lnk`) targets are not resolved in step 4.** The Shell Link format is binary;
    parsing it is a commit of its own with its own risk analysis (a size limit, strict
    validation of every structure, no guessing on malformed data).
30. **The state is the file's flag in `Explorer\StartupApproved\StartupFolder`** of the same
    hive (`HKCU` for the user folder, `HKLM` for the common one), matched by file name
    ignoring case, with the rules of item 21 (`registry.approved_state()`, shared with Run):
    an unknown flag skips the file (item 12); a flag key that cannot be read makes the state
    of the whole folder unknown (one skip for the key, no items). Flags are read only for a
    folder that has files.
31. **The digest covers the file bytes and its flag** (length-prefixed, a missing flag
    included), so a changed file or a changed flag counts as a changed entry. Startup folder
    items are read-only in step 4 (item 9): `disableable` is false.

## Addendum (step 4, XDG fix): directories that cannot be listed

32. **An autostart directory that exists but cannot be listed is a skip, never silence**: one
    `cannot read: <reason>` per directory, reported before the skipped entries; a missing
    directory is simply empty. As the directories overlay each other, nothing the unlisted one
    could change is shown (item 12):
    - the user directory: no items at all, since a stub we cannot see may hide any system
      entry;
    - system directory *k*: names found in the directories before it are shown, with their
      user overrides and correct `shadows`; names found only after it are not (an entry of the
      same name in *k* would replace them); a user entry without a system file before *k* is
      not shown either (it may shadow a file in *k*, so `shadows` is unknown). `shadows=None`
      therefore always means "replaces nothing".
    Later directories are still listed, so every directory that cannot be listed is reported.
    Startup folders follow the same rule (item 30: an unreadable flag key hides the folder).
