# 0017. Organize on Windows: the share-mode check, renames tried again, a path limit, synced folders refused

- Status: accepted
- Date: 2026-11-03
- Builds on: 0011 (the registry), 0012 (items 5, 7, 14, 18, 19, 27, 30, 37-39 and "Why macOS
  and Windows are refused"), 0015, 0016
- Amends: 0012 items 37 and 38 (Windows loses every blocker of its column, and the table two
  of its rows), item 5 (a reason to stay, `path_too_long`, on Windows only), item 7 (a reason
  to refuse a folder, `cloud_sync`), items 18 and 19 (on Windows a directory with a reparse
  point is a link), item 27 (on Windows a rename refused by another program's handle is tried
  again before it fails)

## Context

0012 refused organize on Windows for four blockers, said what would lift each, and asked for
a decision that reviews every blocker of the system's column, with the system in CI (item
38). 0016 lifts the first, `no_open_file_check`: preflight's check (0012 item 19) asks the
share-mode checker, which sees a handle with data access of any process, including one that
shares deletion. This decision reviews the other three and lifts them; CI's Windows job (0015
item 20) runs what only Windows can show.

**Sharing violations.** A file another program opened without sharing deletion cannot be
renamed: `os.rename` raises `PermissionError` (`winerror` 32). The check before the batch
refuses a file held open at that moment; what opens a file afterwards is mostly short-lived:
an antivirus, the search indexer, Explorer making a thumbnail. A rename that meets such a
handle is tried again for a few seconds. One that keeps failing ends as 0012 item 27 already
says: forward, it stops the batch and the others go back; back, its file stays at its
destination, its move `done`, and `organize undo BATCH` tries again later. A file is never
left at both paths or at neither: a rename moves it or does not.

**The path length limit.** Without long paths (`LongPathsEnabled`), a path has at most 259
characters and a directory 247 (`MAX_PATH`, 260 with the terminating zero, less twelve for a
directory's short name); with them, the move succeeds and leaves a file that Explorer, Office
and older programs may fail to open. Organize therefore never makes a path past the limit,
whether long paths are enabled or not: a file whose destination would pass it stays, with a
reason of its own, before anything is looked at there. Undo moves a file back to a shorter
path and needs no such reason.

**Synced folders.** OneDrive's Known Folder Move puts Desktop, Documents and Pictures into
OneDrive, often during setup, and a move there is a sync operation that reaches every device
of the user. Windows names the folders its sync clients keep: OneDrive sets the `OneDrive`,
`OneDriveConsumer` and `OneDriveCommercial` variables, and every client of the Cloud Files
API (OneDrive, Dropbox, iCloud, Box, Google Drive, ...) registers its root under
`SyncRootManager`. A folder inside one is refused as a whole, as a game library is (0012 item
8): the other folders, Downloads first, are sorted. Linux has no such registry, and a folder a
client syncs there is sorted as before; the system does not move the user's folders into one.

**Junctions.** On Windows a directory can lead elsewhere without being a symbolic link: a
junction or a mount point is a directory with a reparse point, which `lstat` reports as a
directory. The folder and the directories above it are resolved (0012 item 7, `link`); a
category directory is looked at with `lstat` (items 18 and 19), so a junction there would take
the files elsewhere. On Windows a directory with a reparse point is not a directory for
organize.

What stays: `cloud_sync` remains for macOS, with `no_open_file_check`; macOS is not built or
claimed (0015). Names that ignore case, `desktop.ini` and `Thumbs.db`, and a destination that
`os.rename` refuses to replace were never blockers (0012).

Every numbered item below is a behaviour a test can show, and is cited by one (item 15).
This machine runs Linux and checks the same code with a Windows scan context and fakes; the
live tests run on CI's Windows job.

## Windows sorts

1. **Nothing blocks Windows any more.** Windows's column of 0012 item 38 is empty:
   `blockers("windows", checker)` is empty with a reliable checker, and is
   `no_open_file_check` alone with an unreliable one, as on Linux. With `ShareModeChecker`
   (0016), `organize move` and `organize undo` run on Windows, and so does the window's
   Organize page.
2. **The table loses two rows.** `sharing_violations` and `path_length_limit` are no longer
   members of `Blocker`, and their lines, labels and translations are gone. `cloud_sync` stays,
   for macOS only: macOS is refused as before, with the lines of `no_open_file_check` and
   `cloud_sync`.

## Sharing violations

3. **A rename refused by a handle is tried again.** On Windows every rename of organize
   (forward, back in a rollback, and in an undo batch) that raises `PermissionError` (a
   sharing or lock violation, or access denied, which an antivirus causes for a moment) is
   tried again after 0.1, 0.2, 0.4, 0.8 and 1.6 seconds: six tries, about three seconds at
   most. Any other error, and the sixth `PermissionError`, is the rename's error, as before. The
   rename is `organize.platforms.renamer(platform)`; on Linux and macOS it is `os.rename`,
   tried once.
4. **What keeps failing ends as 0012 item 27 says.** A move that still fails stops the batch
   and the moved files go back newest first, each with the same tries; a move back that still
   fails leaves its file at its destination, its move `done` and the batch `failed`, and the
   output names the file and `kresorter organize undo BATCH`. Nothing is tried again after the
   batch ends; recovery renames nothing (0012 item 31).
5. **The share-mode check runs right before the batch** (0012 item 19): a file another process
   holds stays, refused `open_file`, whether or not that process shares deletion; the check
   asks for no access that could disturb the holder (0016 item 3).

## The path limit

6. **On Windows a move never makes a path past the limit.** A file whose category directory
   `<folder>\<Category>` would have more than 247 characters, or whose destination
   `<folder>\<Category>\<name>` more than 259, counted in UTF-16 code units as Windows counts
   them, stays (`path_too_long`), with or without `LongPathsEnabled`. The detail is
   `<category path>: <length> > 247` for the directory, checked first, or `<length> > 259` for
   the destination. It is decided before the category path and the destination are looked at,
   so neither is asked of the system. On Linux and macOS no file stays for its length.
7. **A reason of 0012 item 5's pinned set.** `path_too_long` comes after `program` and before
   `conflict`; companions of a file that stays for its length stay with it (`companion`, 0012
   item 14), and the window names it in English and Russian.

## Synced folders

8. **A folder a sync client keeps is refused as a whole** (`cloud_sync`, a reason of 0012
   item 7): the folder, or a directory above it, is a synced folder; the detail is that synced
   folder. Paths are compared ignoring case, as NTFS compares them. It is checked after
   `not_a_directory` and before `cache_or_temp`; the window names it in English and Russian.
9. **The synced folders are those Windows names**: the values of the `OneDrive`,
   `OneDriveConsumer` and `OneDriveCommercial` variables, and every string value (`REG_SZ`, or
   `REG_EXPAND_SZ` with its `%NAME%` variables expanded) of every
   `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager\<root>\UserSyncRoots`,
   whichever user it names (another user's folder is in another profile). A missing key names
   none; a value of another kind is not a path and is skipped.
10. **Asked when organize plans a folder, failing closed.** `ScanContext.synced`, a required
    field like `platform` (0012 item 39), answers the synced folders:
    `organize.synced.WindowsSyncedFolders` on Windows, reading the environment and the
    registry each time organize plans a folder and at no other time; `NoSyncedFolders`, which
    names none, on Linux and macOS, and in a context made for another system than the one
    running, as its open-file check (0016 item 5). A key that exists but cannot be read refuses
    every folder, `cloud_sync` with the detail `synced folders unknown: <message>`.

## Junctions and the folder's name

11. **On Windows a directory with a reparse point is a link.** A category path whose `lstat`
    has `FILE_ATTRIBUTE_REPARSE_POINT` (a junction, a mount point) keeps its category in place
    (`category_blocked`, 0012 item 18) and, appearing after the plan, refuses its files at move
    time and stops a batch, as a category path that is not a directory does (0012 items 19
    and 26). On Linux and macOS a directory is what `lstat` says.
12. **A folder named in another case is that folder.** On Windows, when the path the user
    gives differs from the one the system resolves only in case, organize takes the system's
    spelling: `C:\Users\Ann\downloads` is sorted as `C:\Users\Ann\Downloads`. A short name
    (`ANN~1`), a `subst` drive or a mapped network drive leads elsewhere and is refused `link`,
    with the path it stands for (0012 item 7).

## On Windows itself

13. **Live on Windows** (skipped elsewhere), in a temporary profile: `kresorter organize move
    --yes` sorts a made-up folder and `kresorter organize undo --yes` puts every file back with
    its `mtime_ns`; a file a child process holds open stays `open_file`; a batch whose rename
    meets a file this process holds open moves it once the file is closed between two tries,
    and stops and rolls back when it is held through all six; a file whose destination would
    pass 259 characters stays `path_too_long`; a junction where a category directory would be
    keeps its category in place; a folder under the `OneDrive` variable is refused
    `cloud_sync`.
14. **The README**: organize moves files on Linux and Windows, not on macOS; on Windows it
    refuses folders a sync client keeps and leaves a file whose new path would pass 259
    characters.

## The meta-test

15. **Every item of this decision is cited by a test** as `[0017.N]`. A meta-test fails on an
    item no test cites, on a citation of an item that does not exist, and on an item still
    listed as pending although a test cites it; the pending list starts with every item and is
    empty after the last commit of this decision's plan. The meta-test checks the rules of
    `tests/support/decisions.py` on made-up items and citations, and that check cites this
    item.

## Plan (line 10 of the step 8 plan of 0015)

After the plan of 0016. Each line is one commit or one test/fix pair (red, then green). The
items in brackets leave the pending list in that commit, and no earlier test cites them.

1. The meta-test, every other item pending [15].
2. Renames tried again on Windows, and what keeps failing [3, 4].
3. The share-mode check before a batch [5].
4. The path limit [6, 7].
5. Synced folders [8-10].
6. Junctions, and the folder's name as the system spells it [11, 12].
7. Nothing blocks Windows: the table, the refusal and the Organize page [1, 2].
8. The live tests, run by CI's Windows job once the repository is on GitHub [13].
9. The README [14].

## Accepted limitations

- **A handle opened after the last try**: a file opened without sharing deletion during the
  batch, and held for more than three seconds, stops the batch; a move back held that long
  leaves the file sorted until `organize undo`.
- **Clients Windows does not know**: a folder synced by a client that registers no Cloud
  Files root and is not OneDrive (a client's own virtual drive, an older client) is sorted,
  and the client syncs the moves, as on Linux.
- **Long paths never made**: with `LongPathsEnabled`, a file that could move stays all the
  same when its new path would pass 259 characters.
- **The quarantine does not ask the synced folders**: a scan only looks where the user points
  it, and a junk file found in a synced folder goes to the vault like any other, which the
  client syncs as a deletion until it is restored.

## The owner's answers

- Organize on Windows in 0.1.0, with whatever it needs; how is this decision's (2026-11-03).
