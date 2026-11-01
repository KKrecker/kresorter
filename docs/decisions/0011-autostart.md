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
     Enable moves the stub to the autostart store (item 66); the system file was never touched.
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

## Addendum (step 4, commit 8): services

The `Registry` protocol gains `subkeys()` (the names of the keys below a key) with the rules
of `values()` and of items 24–25: a missing key is `None`, any other failure a `RegistryError`.

33. **Services are read only with `--include-machine`.** They live in
    `HKLM\SYSTEM\CurrentControlSet\Services` (item 5); without consent the registry is not
    touched at all. Every service is `system` scope and read-only in step 4 (item 9).
34. **An autostart service is a Win32 service with `Start=2` (automatic)**: `Type` has `0x10`
    (own process) or `0x20` (shared process), and may also carry `0x40` (per-user service
    template) and `0x100` (interactive). It is listed as enabled. Not autostart entries, and
    not listed nor skipped (they would be hundreds of lines of noise): `Start=3` (manual) and
    `Start=4` (disabled), drivers (`Type` `0x1`/`0x2`/`0x4`/`0x8`), per-user instances (bit
    `0x80`; their template is listed), and a key without `Type`.
35. **Parsing is strict; a violation is a skip with its reason**: `Type`, `Start` or
    `DelayedAutostart` not a `REG_DWORD`; no `Start` or no `ImagePath`; `Start` `0`/`1` on a
    Win32 service (boot and system starts are for drivers only); an unknown `Start` value or
    unknown bits in `Type`; an `ImagePath` that is not a string or is empty. `Type` is checked
    first and `Start` next, so a manual or disabled service is never checked further.
36. **`command` is `ImagePath` as written** (`REG_EXPAND_SZ` kept unexpanded); `name` is the
    key name. `DisplayName` is not read: it is often a resource reference
    (`@%SystemRoot%\...dll,-123`), not a name.
37. **Notes**: `shared process` (`0x20`), `per-user service template` (`0x40`),
    `delayed start` (`DelayedAutostart=1`), in that order. Services are ordered by key name,
    ignoring case.
38. **The digest covers `Type`, `Start`, `ImagePath` and `DelayedAutostart`** (a missing one
    included), nothing else. A `Services` key that cannot be read is one skip; a service key
    that cannot be read skips that service only.
39. **Accepted limitations** (to revisit after the first live run on Windows):
    - trigger-start services (`TriggerInfo`, usually `Start=3`) are not shown, although they
      start on events;
    - for a service in a shared `svchost` process `Parameters\ServiceDll` is not read, although
      the service's code lives there: the user sees the `svchost` entry, not what it runs, and
      no output may present it as a full analysis;
    - `Group` and `DependOnService` are not taken into account.

## Addendum (step 4, commit 9): scheduled tasks and launchd

40. **Accepted limitations** (to revisit after the first live run on each system):
    - scheduled tasks: `StartBoundary`/`EndBoundary` and start delays are not taken into
      account; the registry cache of the Task Scheduler (`TaskCache`) is not compared with
      the XML definitions.
    - launchd: the state comes from the file's `Disabled` key only. launchd keeps overrides of
      its own (`launchctl enable/disable`) in `/var/db/com.apple.xpc.launchd/`, readable by
      root only; they are not read, so every launchd item carries the note
      `state from the file`. Run as root, the real state could be checked there; it also
      changes at runtime, even between two readings. `LimitLoadToSessionType` is not taken
      into account; `/System/Library/LaunchAgents` and `LaunchDaemons` are not read.

### Scheduled tasks (9a)

41. **Task definitions are read only with `--include-machine`.** They are XML files under
    `%SystemRoot%\System32\Tasks` (`%windir%` if unset), machine-wide, mostly readable only
    by administrators; every item is `system` scope and read-only in step 4 (item 9).
42. **A task is an autostart entry if it has a `BootTrigger` or a `LogonTrigger`.** Tasks with
    other triggers only (time, calendar, idle, event, registration, session state) are not
    listed nor skipped, like manual services (item 34).
43. **`name` is the task path** as the Task Scheduler shows it (`\Microsoft\Windows\...`);
    folders are read recursively, linked folders are not followed (skipped as `not a regular
    file`). Order: by name, ignoring case.
44. **Notes and state.** `at boot`, `at logon` or `at logon of <UserId>`, boot first; a trigger
    with `Enabled=false` gets ` (trigger disabled)`; `Settings/Enabled=false` adds
    `task disabled`. `enabled` is: the task is enabled and at least one boot or logon trigger
    is. Booleans follow `xs:boolean` (`true`, `false`, `1`, `0`); anything else is a skip.
45. **`command` is the first action as written**: `Exec` is `Command` and `Arguments`
    (`%VAR%` kept unexpanded); more actions add `N more action(s)`. A `ComHandler` is
    `COM handler {CLSID}` with the note `COM handler, not resolved`. Other actions
    (`SendEmail`, `ShowMessage`) are skipped as `unsupported action`.
46. **Parsing is strict and bounded**: invalid XML, a root that is not `Task` in the Task
    Scheduler namespace, no actions, an empty `Command` or a `ComHandler` without `ClassId`
    are skips; only regular files of at most `MAX_ENTRY_BYTES` are opened. **A DTD is refused**
    by a first expat pass before the tree is built, so no entity is ever expanded and no
    dependency is added. UTF-16 with a BOM (as Windows writes tasks) and UTF-8 are read alike.
47. **Tasks do not overlay each other**, so a folder that cannot be listed is one skip with its
    reason and the other folders are still read (unlike XDG, item 32). The digest covers the
    file bytes.

### LaunchAgents and LaunchDaemons (9b)

48. **Where launchd entries are read**: `~/Library/LaunchAgents` (`user` scope),
    `/Library/LaunchAgents` and `/Library/LaunchDaemons` (`system` scope), without a flag, like
    `/etc/xdg`: item 5 is about `HKLM` only. `/System/Library` is not read: it is the OS
    itself, protected by SIP, hundreds of entries the user cannot change. Daemons share
    `Source.LAUNCH_AGENT` and carry the note `daemon, started at boot`. Order: user agents,
    system agents, daemons; by file name, ignoring case, within a directory.
49. **One item per `*.plist`**, as launchd loads them all; other files are not entries. The
    notes say whether it also starts: `runs at load` (`RunAtLoad`), `kept alive`
    (`KeepAlive=true`), `kept alive on conditions` (a non-empty `KeepAlive` dictionary),
    otherwise `loaded at login, started on demand` — listed with a note, not hidden, like the
    non-service systemd units (item 18).
50. **`name` is the `Label`; `command` is `shlex.join` of the argv launchd runs**:
    `ProgramArguments`, with `Program`, if present, as the executable in place of its first
    element; `Program` alone is the command.
51. **Parsing is strict and bounded.** XML and binary property lists are read; `plistlib`
    refuses XML entity declarations. A root that is not a dictionary, no or an empty `Label`,
    neither `Program` nor `ProgramArguments`, wrong types of `Program`, `ProgramArguments`,
    `RunAtLoad`, `Disabled` or `KeepAlive`, an empty command, a file over `MAX_ENTRY_BYTES` or
    not a regular file are skips. `plistlib` is not hardened against malformed input (it also
    fails with `ExpatError`, `ValueError`, even `AttributeError`), so any failure to parse the
    at most `MAX_ENTRY_BYTES` read is the same skip, `not a valid property list`.
52. **The state is the file's `Disabled` key** (`Disabled=true` is disabled, with that note);
    every item carries `state from the file` (item 40). launchd directories do not overlay each
    other: one that cannot be listed is a skip with its reason, the others are still read. The
    digest covers the file bytes; launchd items are read-only in step 4 (item 9).

## Addendum (step 4, commit 10): `safeclean autostart list`

53. **One listing per platform, from its readers, joined in order**: Linux XDG autostart, then
    systemd user units; Windows Run keys, startup folders, services, then scheduled tasks;
    macOS launchd. An `AutostartContext` names everything read from the live system (platform,
    environment, home, root, a registry factory), so the whole listing runs on temporary trees
    and a fake registry in tests.
54. **The registry is created on Windows only, once per listing**, by a factory (`WinRegistry`
    on a live system); Linux and macOS never touch it. `--include-machine` changes nothing on
    Linux and macOS, where no machine scope needs consent, and is accepted silently. The
    caller detects the platform: `autostart.listing` does not depend on the CLI.
55. **`safeclean autostart list [--json] [--include-machine]` reports only**: it creates,
    changes and deletes nothing (not even the data directory), builds no scan context and
    always exits with 0 once it has listed; `safeclean autostart` without an action is a
    usage error (2). The text groups entries by source in reader order, each with its state
    and scope, `command`, `location`, `shadows` if any and every note, then the skips. On
    Windows without `--include-machine` a note says what was not read. JSON has `platform`,
    `include_machine`, every item field and the skips.
56. **`disableable` is shown since `autostart disable` exists** (commit 12c1; it was hidden
    before, so the report would not promise an action it could not take): the text adds
    `disableable` to the marks of an entry, JSON has the field. It means the source can be
    written (item 8), not that the action will pass: enabling an entry disabled elsewhere is
    still refused (`foreign`, item 74). The report reads the system, not the journal, so it
    cannot know that in advance.

## Addendum (step 4, commit 11): journal schema v3

57. **A table of its own, `autostart_changes`**, with its own `state` (`pending`, `done`,
    `failed`, `rolled_back`), not new kinds of `operations`: a `CHECK` cannot be changed by
    `ALTER TABLE` in SQLite, and rebuilding `operations` would mean switching off the foreign
    keys of `items`, which cannot be done inside a transaction. Quarantine operations and
    autostart changes are different domains; separate tables keep the quarantine journal
    untouched by the migration.
58. **`entry` and `location` are kept apart**: `entry` is what the user saw in the listing,
    `location` is what is actually written. A user XDG file is both; for a system XDG entry,
    `entry` is the file in `/etc/xdg/autostart` and `location` the user stub; for `HKCU` Run,
    `entry` is the `Run` value and `location` its `StartupApproved\Run` flag. The journal
    itself shows that the system file and the `Run` value are never written.
59. **The bytes before and after are stored in full**, at most 64 KiB each (the XDG read
    limit); `NULL` means the entry does not exist. For XDG the original still goes to the
    vault (`vault_path`) and the journal copy is only for reconciling with the disk; for the
    registry the journal is the source of the rollback (a `StartupApproved` value is 12
    bytes). A change that changes nothing (equal values, both `NULL` included) is refused by
    the schema.
60. **Only writable sources can be journaled**: `source` is limited by a `CHECK` to
    `xdg_autostart` and `run_key` (item 8), so a read-only source cannot be written even by
    a mistake in the code; making another source writable needs a migration that rebuilds
    this table. `digest` (the entry as listed and checked again right before acting) is 32
    lowercase hex characters; the table is `STRICT`.
61. **The journal API and its reconciliation in `recover()` come with the changes
    themselves** (commit 12: 12a writing and journaling, 12b `recover()`, 12c the CLI with
    `disableable`), since reconciling depends on the exact order of the write steps.
62. **Unfinished work blocks both domains**: a pending autostart change refuses new
    quarantine operations until `recover()` has run, and a pending quarantine operation
    refuses autostart changes, as `_require_no_pending` does today. Both write to one journal
    and must not interleave halfway.

## Addendum (step 4, commit 12a1): what an XDG entry becomes when disabled

63. **A user's own entry is replaced by a copy with `Hidden=true`** (`hidden_copy`): every
    other byte is kept, so enabling only has to put the original back. An existing `Hidden`
    line of the `[Desktop Entry]` group is replaced in place with its line ending; otherwise
    one is added right after the group header, with the header's line ending. Comments and
    later groups (`[Desktop Action ...]`) are not touched.
64. **The copy is checked by the reader's own rules**: `parse_keys` (shared with the reader,
    which stays read-only) validates the entry, and the text is split into lines exactly as
    `parse_keys` splits it: the split matches the reader (`str.splitlines` after UTF-8), not
    `bytes.splitlines`, which misses `\x0b`, `\x85`, `\u2028` and the like and would add a
    second `Hidden` the reader skips as broken. So the copy reads back with the same keys and
    `Hidden=true`. An entry already `Hidden=true` is refused (nothing would change, item 59);
    so is a copy that would be larger than `MAX_ENTRY_BYTES`, which the reader would skip.
65. **A system entry is hidden by `STUB`**, `[Desktop Entry]` and `Hidden=true` only, in the
    user directory under the same file name; it reads back as the system entry, disabled, with
    the system file in `shadows`.

## Addendum (step 4, commit 12a2): disabling an XDG entry

66. **The autostart store, `<data_dir>/autostart/<change id>`, mode 0700**, is apart from the
    quarantine vault: it holds the originals of disabled entries and the stubs removed on
    enable (refining item 8, "through the quarantine"), both journaled in `autostart_changes`.
    Originals are needed for enable at any time, so the store is never purged:
    `delete_from_vault` refuses anything outside `<vault>/<operation>/<item>`.
67. **A user's own entry is never missing**: the copy is written to `<id>.new` in the store
    and synced, the original is hard-linked into the slot `<id>` (the same inode, not a copy),
    and `os.replace` puts the copy in its place atomically. The copy is made of the bytes read
    once and journaled as `value_before`, never read again while writing.
68. **A system entry gets a stub created with `O_CREAT | O_EXCL`**, so a file that appeared
    meanwhile is never overwritten. A missing user directory is created with mode 0700 (XDG
    Base Directory); an existing one keeps its mode. A directory created for a change that is
    rolled back stays: removing it would be a deletion, and an empty directory is harmless.
69. **Checked again right before acting, as a whole**: the item must still be in a fresh
    `read_xdg` listing, equal field by field, which also catches a user entry or stub that
    appeared over a listed system entry; the bytes of a user entry are compared with the
    listed digest once more. The window between this check and `os.replace`/`O_EXCL` remains,
    as in the quarantine, with the same compensations.
70. **Refusals are results, not exceptions, and change nothing**: no row, no file, nothing in
    the store. `read_only` (item 9), `changed`, `already` (disabled by `Hidden=true`,
    `X-GNOME-Autostart-enabled=false` or a stub), `pending` (unfinished autostart change or
    quarantine operation, item 62), `other_device` (the store cannot hold the original by a
    link), `too_large` (the copy would be skipped by the reader, item 64).
71. **Journal before change**: the `pending` row with both values exists before the disk is
    touched, and becomes `done` after the last step.
72. **A failure is rolled back without deleting anything**: when a step fails the entry is as
    it was; a stub created but not written or synced is moved into its slot (`vault_path`).
    The row is `rolled_back` only if the location holds what it held before (`value_before`,
    or nothing); otherwise it is `failed` and left for `recover()`. An OS error is returned as
    the result; any other exception (`KeyboardInterrupt`) is journaled the same way, then
    raised.
73. **Leftovers stay in the store**: a partial `<id>.new` after a failed write, or the slot of
    an original linked before `os.replace` failed. The store is ours and nothing deletes;
    `recover()` reconciles them (commit 12b).
74. **Enabling an entry not disabled by safeclean is refused in step 4** (commit 12a3): a
    user's own entry with `Hidden=true` or `X-GNOME-Autostart-enabled=false` and no journal
    row would need its content edited. A user stub over a system entry can be enabled: it is
    moved, not edited.

## Addendum (step 4, commit 12a3): enabling an XDG entry

75. **A user's own entry gets its original back, never missing in between**: the copy is
    hard-linked into the slot of the enable, then `os.replace` moves the original from the
    slot of the disable to its place (the same inode it had before the disable). The slot of
    the disable is then empty; its `disable` row stays as history. Disable and enable can be
    repeated, each with its own slot.
76. **"Disabled by safeclean" is decided by the journal, not by the file**: the last `done`
    change at this location must be the `disable` of an own entry, and its `value_after` must
    equal the file byte for byte. An enable after it, an edited copy, or no row at all is
    `foreign` (item 74); `rolled_back` rows do not count. The journal is the only source of
    truth about what safeclean did.
77. **The original in the store is checked against `value_before` byte for byte** before it
    is put back; missing or different is `original_changed`, so a substituted file never
    reaches the entry's place.
78. **A stub is a user entry without `Exec`** (the reader shows it only with `Hidden=true`
    over a system entry). It is enabled by moving it to the store, without consulting the
    journal: nothing is edited, so a user's own stub (even with other keys such as `Name=`)
    is enabled like one made here.
79. **The entry's bytes are read once, by one check shared by both actions**, after the
    listing is compared: they are compared with the listed digest and are the bytes
    journaled. Disabling a system entry now also reads its file again and compares it.
    The refusals are those of item 70, plus `already` for an enabled entry, `foreign` and
    `original_changed`; failures are rolled back as in item 72.

## Addendum (step 4, commit 12a4a): writing the registry

80. **Writing is one value under `HKCU`, and nothing else**: the `UserRegistry` protocol adds
    a single method to `Registry`, `set_user_value(key, value)`, without a hive parameter,
    so nothing in safeclean can write `HKLM`; the ban is in the API itself, like the closed
    list of sources in the schema (item 60). There is no method to delete a value or a key.
    `WinRegistry` opens the key with `CreateKeyEx(HKEY_CURRENT_USER, key, 0, KEY_SET_VALUE |
    KEY_WOW64_64KEY)`, creating it if it is missing, writes with `SetValueEx` and closes the
    key whatever happens once it was opened; a failure is a `RegistryError` with the reason.

## Addendum (step 4, commit 12a4b): the `HKCU` Run `StartupApproved` flag

81. **One journal for both kinds of change**: the row of `autostart_changes` is written and
    finished by shared functions of `autostart.changes` (`insert_change`, `finish_change`,
    `has_pending`, `refused`), used by `XdgChanges` and `RunKeyChanges` alike, so the order
    "journal, then act, then finish the row" exists once.
82. **The Run value is never written, only its flag**: disabling writes to
    `HKCU\...\Explorer\StartupApproved\Run` the bytes the Task Manager writes, `03 00 00 00`
    followed by the FILETIME of the change (`now // 100 + 116444736000000000`, little-endian);
    enabling writes `02` followed by eleven zero bytes. Values read as `06`/`07` are recognized
    as before (item 21); the bytes found before the change are kept in
    `value_before` of the journal.
83. **A missing flag means enabled**: disabling it creates the flag; enabling writes `02`
    and never deletes a value, even when there was no flag before the disable (nothing in
    safeclean can delete a value, item 80).
84. **A value disabled by the Task Manager can be enabled**: unlike an XDG entry disabled
    elsewhere (item 74, `foreign`), the flag is the single, documented switch the Task Manager
    itself flips back; enabling it edits nothing else, so it is not refused.
85. **The value is checked again right before writing**: the Run keys are read again with
    `read_run_keys` and the item is found by its digest, so an unnamed value and one named
    `(Default)` stay distinct; a value that differs from the listing is `changed`. Only an
    `HKCU` Run value can change (`read_only` otherwise: `HKLM`, `RunOnce`, other sources).
    The window between the check and the write remains: the registry has no compare-and-swap,
    and the compensation is the same as in quarantine (journal first, state read back).
86. **Journal fields**: source `run_key`, entry the Run key path with the value name as
    listed (`(Default)` for the unnamed value), location the `StartupApproved` path with the
    exact name of the flag written: the unnamed flag is the path ending with the key's
    backslash, so it is never taken for a value literally named `(Default)`, which writes
    another flag (commit 12b1). The name is what follows the fixed prefix, so a backslash
    inside a value name does not matter. `vault_path` is NULL: nothing is kept in the
    store, the previous bytes are in the row itself.
87. **A failure is read back, not assumed**: a `RegistryError` from the write is a result,
    not an exception; the flag is then read again, and the row is `rolled_back` if the flag
    is still what it was, `failed` otherwise. If the flag cannot be read back, the row stays
    `pending` and the error is raised: `recover()` (commit 12b) reconciles it, the outcome of
    a write that cannot be read is never guessed. The clock (`now`) is injectable for tests.

## Addendum (step 4, commit 12b2): recovering `HKCU` Run changes

88. **A pending `run_key` row is closed by the flag it names**: `RunKeyChanges.recover()`
    reads the flag at the row's `location` (by name, ignoring case, item 86) and closes the
    row `done` if it holds the bytes after the change, `rolled_back` if it holds the bytes
    before (a missing flag is `NULL`), `failed` otherwise, with the reason in `error`. As in
    item 72, the journal records what is in the registry, not what was intended.
89. **`recover()` only reads the registry**: a change found written is not undone and one
    found not written is not redone; the user asked for it once and can ask again.
90. **An unreadable flag is never guessed**: the `RegistryError` is raised and the row stays
    `pending` (item 87); rows already closed before it stay closed.
91. **Only pending `run_key` rows are touched**: XDG rows are recovered by `XdgChanges`
    (commit 12b3), and finished rows, `failed` included, stay as they are: the registry has
    no store, so there is nothing left to reconcile. Nothing pending reads nothing.
92. **The report is `ChangeRecovery`**: the ids of the closed changes, as `done`,
    `rolled_back` and `failed`, shared with the XDG recovery. Once nothing is pending,
    changes are allowed again (item 62).

## Addendum (step 4, commit 12b3): recovering XDG changes

93. **A pending XDG row is closed by the disk**: `XdgChanges.recover()` reads the entry at the
    row's `location` and closes the row `done` if it holds the bytes after the change and the
    store holds what the change kept there (`vault_path`, when set, holds the bytes before),
    `failed` if the entry is as after but the store does not hold them, `rolled_back` if the
    entry is as before, `failed` otherwise; the reason is in `error`. As in item 72, the
    journal records the disk, not the intent.
94. **Nothing is redone or undone**: a staged `<id>.new` is never put in place, and a link
    or a copy left in the store stays there; the store is never purged (item 66). Whether to
    change the entry again is the user's decision (item 89).
95. **A failed row is looked at again only while it is the last change at its location**:
    otherwise the disk shows a later change, not this one. If it is still neither as before
    nor as after, it stays `failed` with its first error and is not reported.
96. **A stub left by a double fault is moved to the store**: when writing (or syncing) a
    stub failed and moving it to the store failed too, the row is `failed` with the stub in
    place. If what is there is a strict beginning of `STUB`, `recover()` journals the slot
    `<id>` as `vault_path` first, then moves the stub there, never deleting it, and the row
    is `rolled_back`. A stub that is complete (only its `fsync` failed) is as after the
    change: the row is `done`.
97. **An entry that exists but cannot be read is never guessed**: a missing entry is a known
    state (`NULL`), but anything else that is not a readable entry (a directory, a file
    larger than 64 KiB, a file that cannot be opened) raises `BrokenEntryError` with the
    reason, and the row stays as it is. Since a pending row blocks new changes (item 62),
    autostart changes stay blocked until the user removes or fixes what is there: a strange
    file in place of an entry is not a case for guessing.
98. **Only XDG rows are touched**: rows of `run_key` are recovered by `RunKeyChanges`
    (item 91), and the report is the same `ChangeRecovery` (item 92).

## Addendum (step 4, commit 12b4): one rule for unfinished work

99. **`storage.pending.has_pending` is the rule of item 62, once**: it is true while the
    journal holds a pending quarantine operation or a pending autostart change, and both
    `QuarantineService` (quarantine, restore, plan and purge) and the autostart changes
    refuse new work while it is. It lives in `storage`, so the quarantine does not import
    the autostart package. The quarantine error now says "unfinished work", since an
    autostart change may be what blocks it.
100. **Each `recover()` reconciles its own domain and is never blocked**: the quarantine's
    `recover()` leaves autostart changes alone, and the autostart ones leave quarantine
    operations alone (items 91, 98); a `recover()` refused because of the other domain
    would leave no way out.

## Addendum (step 4, commit 12c2a): `safeclean autostart recover`

101. **One journal session for every command that acts**: `cli_journal.with_journal` checks
    the data directory before creating anything (decision 0009), takes the single-instance
    lock and opens the journal there; the quarantine commands and the autostart commands
    that act share it, so both domains write one journal (item 62). These autostart commands
    build the scan context to find the data directory; `autostart list` still does not and
    opens no journal (item 55).
102. **`safeclean autostart recover` reconciles the autostart changes of this platform**:
    XDG on Linux, `HKCU` Run on Windows, nothing on macOS, where nothing can be written. It
    prints `Nothing to recover.` or each closed change as `[id] done|rolled_back|failed`
    and exits with 0. It is a command of its own because each domain recovers its own
    (items 100, and decision 3(b) of 12c): the autostart domain needs a command that opens
    the journal without changing an entry.
103. **An unfinished change that cannot be checked stops it with exit 3**: the reason
    (`BrokenEntryError` or `RegistryError`, items 90, 97) is printed with what to do (fix or
    move what is there, then run `safeclean autostart recover` again); the row stays as it
    is. A data directory, lock or journal that cannot be used is exit 3, as in quarantine.
104. **Quarantine actions wait for it, by name**: after its own `recover()`, a quarantine
    command that would act (`add`, `restore`, `purge`) and finds unfinished work, which can
    then only be an autostart change, exits with 3 and names `safeclean autostart recover`;
    nothing is changed. `quarantine list` reads only and still runs.
105. **The registry of a listing context is a `UserRegistry`**: the same factory gives the
    registry the listing reads and the one a change writes; `WinRegistry` is both, and
    tests use one `FakeRegistry` for both.

## Addendum (step 4, commit 12c2b): `safeclean autostart disable|enable ID [--yes]`

106. **The id is the beginning of the digest**: `autostart list` shows its first 12
    characters as the last line of each entry; the command takes any beginning of 1 to 32
    hex digits, in any case (anything else is a usage error, exit 2). An entry changed since
    it was listed has another digest, so its old id names nothing: "may have changed since
    it was listed", exit 1. A beginning that names several entries is refused (exit 1) and
    asks for more of it. Only the user's scope is listed for it: machine-wide entries are
    read-only anyway (item 9).
107. **The order inside the journal session (item 101)**: the autostart `recover()` first,
    printed only if it closed something; then the listing, the id, read-only sources
    (`Refused: <source> entries are read-only.`), an entry already in that state (nothing to
    do); all of these exit with 1 and journal nothing.
108. **Without `--yes`, what would be written is shown and nothing is changed** (exit 1, as
    `purge` and `add --from-analysis`): the name, source, scope and location, then, for an
    own XDG entry, the copy with `Hidden=true` and the original kept in the store; for a
    system entry, the stub created in the user directory and the system file never written;
    for enable, what safeclean changed put back, nothing deleted; for a Run value, its
    `StartupApproved` flag set as the Task Manager does, the Run value never written. The
    preview reads no journal: a refusal such as `foreign` comes only with `--yes` (item 56).
109. **With `--yes`, exit codes as in quarantine**: `done` is 0 with the change id; a refusal
    (`Refused: <refusal>: <detail>`) and a `rolled_back` change are 1; a `failed` change is
    3 and names `safeclean autostart recover`; unfinished quarantine work is 3 and names
    `safeclean quarantine list` (items 62, 104); an entry or flag that cannot be checked is 3
    with its reason, as in `autostart recover` (item 103).

## Addendum (step 5.0): after the pre-step-5 audit

110. **A test of an entry that exists but cannot be read fakes the OS error, never `chmod`**:
    it puts something unreadable in its place (a directory, as for item 97) or makes
    `os.stat` and `os.lstat` raise `PermissionError` for that path. `chmod` denies nothing to
    root, which CI containers often are, and a sandbox may not enforce it at all
    (`docs/reviews/pre-step5-audit.md`, section 2): a test built on it can pass without
    checking anything.
111. **"Nothing is there" only for `ENOENT` and `ENOTDIR`** (pre-step-5 audit, A1):
    `recover()` decides that an entry is missing by `lstat` of its location, and the device
    check of item 66 walks up to the nearest directory that exists by `stat`, past these two
    errors only. Any other error (`EACCES`, ...) means that something is there which cannot be
    looked at: the entry raises `BrokenEntryError` with the reason of the read (item 97), the
    device check raises its `OSError` before anything is journaled. `Path.exists()` and
    `Path.is_symlink()` are not used for this: since Python 3.14 they are `False` for any
    error, which made a stub in place that cannot be read look missing and closed its change
    `rolled_back`.
112. **`with_journal` names the data directory only for its own steps** (pre-step-5 audit,
    A2): creating it and taking the lock are `cannot use the data directory`, opening the
    journal is `cannot open the journal`. An `OSError` that the body of a command does not
    handle is exit 3 as `safeclean: stopped: <reason>`: the reason names its path, a wrong place
    is worse than none, and no command is suggested, since for an error nobody foresaw it could
    fail the same way again. The quarantine names its vault when it cannot be created or made
    private: `cannot use the vault: <reason>` (exit 3).
113. **An autostart command says what it could not do** (A2), in two phases, both exit 3: an
    `OSError` from `recover()` (a partial stub that cannot be moved to the store, item 96) is
    `an unfinished autostart change cannot be closed: <reason>; fix or move what is there, then
    run 'safeclean autostart recover' again`, in `recover`, `disable` and `enable` alike, and the
    row stays as it was; an `OSError` from the checks before a disable or enable acts (the
    device check, item 111) is `cannot <action> <name>: <reason>; nothing was changed`, and
    nothing is journaled. Output written after these phases is not part of either.
114. **A journal failure in the middle of a command is exit 3** (pre-step-5 audit, A3 and its
    decision 1): a `sqlite3.Error` raised by the body (a full disk, an I/O error, the journal
    held by another program past the busy timeout) is `safeclean: journal failed: <reason>; run
    '<command>'`. The command is the one that recovers the domain, passed to `with_journal` by
    it: `safeclean autostart recover`, `safeclean quarantine list`. Its end cannot be trusted,
    as with the lock and a `failed` change; a new code would break the 0/1/2/3 contract for no
    gain. A failed transaction is rolled back, and a change left `pending` in the journal is
    closed by `recover()`.
115. **The autostart store is made by the first change** (pre-step-5 audit, B9a), after the
    device check and before the change is journaled, not by `XdgChanges` itself: a preview, a
    refusal or a `recover()` with nothing to close leaves no `<data_dir>/autostart` (item 70:
    nothing in the store, not even the store). Until it is made, the device check of item 66
    compares with the nearest directory above it that exists (item 111), where `mkdir` puts
    it. A store that cannot be made raises its `OSError` before anything is journaled, as a
    check before acting (item 113). So every journaled XDG change has its store, and
    `recover()` never makes it.
116. **The slot of a partial stub is journaled before the stub is moved there** (pre-step-5
    audit, B9b), in `disable` as in `recover()` (item 96): a crash right after the move leaves
    a row that names the slot, never a stub in the store that no row names. If the move then
    fails, `vault_path` names an empty slot; `recover()` reads it as holding nothing, which is
    what the change of a stub keeps, so the row is still closed by the entry in its place.
117. **A step that finds its place taken rolls the change back** (pre-step-5 audit, B9c):
    a `FileExistsError` comes only from `O_EXCL` (the stub, `<id>.new`) and from linking into
    the slot, before the entry is written, so nothing of ours is at its location. A file that
    appeared where the stub goes since the check (item 69) is kept as it is, never overwritten
    (item 68), and the row is `rolled_back` with the error: refining item 72, the change left
    the disk as it found it. It was `failed`, and `recover()` then took an empty or partial
    file of the user's for a partial stub and moved it to the store (item 96).
118. **The data directory's policy lives in `storage.data_dir`** (pre-step-5 audit, B1):
    `check_data_dir` raises `DataDirError`, and `PRIVATE` (0700) is the mode of the data
    directory and of every directory safeclean makes in it (the vault, the autostart store).
    The journal session (`cli_journal`) no longer depends on the quarantine, nor would
    organize; `QuarantineService` keeps its contract and raises `QuarantineError` with the
    same message.
119. **The journal of autostart changes is `autostart.journal`** (B2): `ChangeState`,
    `ChangeRefusal`, `ChangeResult`, `ChangeRecovery`, `Change`, `insert_change`,
    `finish_change` and `refused`, shared by `XdgChanges` and `RunKeyChanges` (item 81), so
    the Run module no longer imports the XDG one; `autostart.changes` keeps the store and the
    XDG changes.
120. **One `insert_row()` for every journal** (B3): `storage.journal.insert_row` runs one
    `INSERT` and returns the id of its row; it is the only place that handles a `lastrowid`
    of `None`, which sqlite3 never returns after a successful `INSERT`. The quarantine and the
    autostart journal use it, and organize will.
121. **The journal's times come from a clock given to the domain** (pre-step-5 audit, B3):
    `QuarantineService`, `XdgChanges` and `RunKeyChanges` take `now` (`storage.journal.Clock`,
    `time.time_ns` by default) and pass it to every journal write; `insert_change` and
    `finish_change` require it, so no journal helper picks a clock of its own and mypy names a
    caller that forgets it. `RunKeyChanges` dates its rows with the clock that dates its flag
    (item 82). A test checks `created_at_ns` and `finished_at_ns` exactly; organize will take
    its clock the same way.
122. **Test helpers used by several files live in `tests/support/`, one module per kind,
    imported by name** (pre-step-5 audit, B10): files first (`write`, `write_desktop`,
    `snapshot`). A helper that does something else under the same name stays in its file: a
    `write` that also sets a time or writes text, the walker's one-byte default, a snapshot
    with inodes. Boundary fakes stay in `tests/fakes.py`. Organize's tests start from these
    instead of adding a seventh copy.
123. **Fixtures used by several files live in `tests/conftest.py`** (B10): `data_dir`, `zone`
    and the CLI's `scan` context, beside `support.journal` (`rows`, `query`) and `support.cli`
    (`scan_context`, `autostart_context`, `run`). pytest finds a fixture by its name, so it is
    not imported: an imported fixture reads as an unused import, and the parameter that
    requests it shadows it. Fixtures that share a name but not a setup stay in their files
    (`conn`: one keeps the journal apart from the tree under test).
