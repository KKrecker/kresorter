# 0012. Organize: sort one folder by kind, journaled, reversible, never overwriting

- Status: proposed
- Date: 2026-11-01
- Builds on: 0001, 0002 (section 3), 0004, 0005, 0007 (rename race), 0008 (single deletion
  point), 0010 (plan, then `--yes`), 0011 (items 57, 124-127), the pre-step-5 audit
  (decisions 3, 4)
- Amends: 0002 (section 3), 0004 (consequences)

## Context

Step 5 adds the third domain that changes the disk: the user chooses a folder (typically
`~/Downloads` or `~/Desktop`) and safeclean proposes to sort its files into category
directories. A file moved away from what expects it is broken as surely as a deleted one, so
the organizer has to know what must not move, say why, and be able to put everything back.

Every numbered item below is a behaviour a test can show, and is cited by one (item 40).
What cannot be tested (context, the reasons behind the platform table, the commit plan,
limitations) is prose.

## Principles

1. **Proposing changes nothing.** Without `--yes`, `organize move` shows the plan and creates,
   moves and journals nothing in the folder; like every command that acts, it still opens the
   journal and recovers first.
2. **One folder, one level.** Only the regular files directly in the chosen folder are
   candidates. Subdirectories are never entered and never moved, whatever they hold: a
   directory is a unit someone built (a project, a game, a saved page, an album).
3. **Moves stay in the folder.** A file goes to `<folder>/<Category>/<its name>`: same name,
   one category directory below, never out of the folder.
4. **Never overwrite, never rename, never delete.** A taken destination leaves the file where
   it is; no suffix is added. Organize has no deletion point: undo leaves the category
   directories, empty ones included, as the vault keeps its empty operation directories (0008).
5. **Every file that stays is reported with its reason** (`StayReason`, a pinned set), never
   skipped in silence. The set, in its order: `not_regular`, `folder_metadata`,
   `in_progress`, `junk`, `unknown_kind`, `companion`, `program`, `conflict`,
   `category_blocked`, and `missing`, which only undo gives (item 30).
6. **Deterministic.** The same folder gives the same plan whatever order the directory is
   listed in: files by name, categories in table order, what stays by reason in the order of
   item 5.

## The folder

7. **The folder must be a real directory the policy allows and the user can list**: not a
   link, not blacklisted (`PathPolicy.check_path`, the data directory included), neither the
   home directory nor above it (its top level holds dotfiles and paths other programs expect),
   and listing it does not fail. Otherwise nothing is planned, and the output is one line,
   `Refused: <folder>: <reason>`, followed by ` (<detail>)` when the reason has one; exit 1.
   `<folder>` is the absolute path. The reasons (`organize.folders.FolderReason`):
   - `not_found`: nothing is there, or a file is where a directory above it should be;
   - `not_a_directory`;
   - `link`: the folder or a directory above it is a link; the detail is where it leads;
   - `blocked`: the detail is the policy's reason (`system`, `app_data`, ...);
   - `home`: the home directory or a directory above it;
   - `unreadable`: the folder cannot be looked at or listed, or one of its entries cannot be
     looked at; the detail is the system's message, after `<name>: ` for an entry;
   - for item 8, `game_library` and `project`, whose detail is the marker that matched, and
     `cache_or_temp`, whose detail is the junk rule. The markers are data
     (`organize/folders.toml`); names are matched with them folded (item 20), and a
     version-control directory is asked of the file system.
8. **A folder whose files break when moved is refused as a whole**, with its reason:
   - a game library: `steamapps`, `SteamLibrary`, `GOG Games` or `Epic Games` among its path
     names, or a `libraryfolders.vdf` in it;
   - a project: a version-control directory (`.git`, `.hg`, `.svn`) in it or in any parent,
     or a build or package file in it (`pyproject.toml`, `package.json`, `Cargo.toml`,
     `go.mod`, `CMakeLists.txt`, `Makefile`, `*.sln`, ...);
   - a cache or temp directory: the directories of a junk rule match the folder.
   The marker lists are data, each entry with an example in a test, like the junk rules.

## What stays

9. **Anything but a regular file stays** (`not_regular`): links are never followed, sockets,
   pipes and devices never touched.
10. **The folder's own metadata stays** (`folder_metadata`): names that start with `.`,
    `desktop.ini`, `Thumbs.db`.
11. **Work in progress stays** (`in_progress`): partial downloads (`*.part`, `*.crdownload`,
    `*.download`, `*.partial`) and Office lock files (`~$*`): a program is still writing them
    or will rename them where they are.
12. **Junk stays** (`junk`): a file a junk rule matches belongs to `analyze` and the
    quarantine, not to a category.
13. **A file of unknown kind stays** (`unknown_kind`): its extension is not in the category
    table. There is no `Other`.
14. **Companions stay together** (`companion`): a file stays when another file with the same
    stem (the name before its first dot) would not go to the same category directory, to
    another one or to none: a video and its subtitles, a photo and its sidecar, a song and its
    cover. Companions of one category move together.
15. **Programs next to their libraries stay** (`program`): when the folder holds a library
    (`.dll`, `.so`, `.so.*`, `.dylib`), its `.exe` files stay too. A lone `.exe` or `.msi` is
    an installer.
16. **Web pages are not in the table** (`unknown_kind`): `X.html` or `X.htm` may load what is
    beside it, a saved page's `X_files` directory or images, so a page stays even alone.
17. **A taken destination leaves the file in place** (`conflict`): anything at
    `<Category>/<name>`, a file, a directory or a link. A destination that cannot be looked at
    counts as taken; the detail is the system's message.
18. **A category path that is not a directory keeps its whole category in place**
    (`category_blocked`): `<folder>/<Category>` is a file or a link, or cannot be looked at
    (the detail is the system's message).
19. **Right before the batch every file is checked as the quarantine checks it** (0004 item
    5): allowed by the policy and not open, the size and `mtime_ns` of the plan, a parent not
    swapped for a link, on the folder's device, its destination still free. A file that fails
    stays, with the reason, reported as refused; the others form the batch. The reasons are
    preflight's (`core.preflight.RefusalReason`), the quarantine's, and one only organize
    gives, `conflict`: the destination is taken since the plan (the detail is its path) or
    cannot be looked at (the detail is the system's message), or the category path is no
    longer a directory (`<category path>: not a directory`). A file on another device than the
    folder is `cross_device`, and so is a category directory on another one (the detail is its
    path); a category path that cannot be looked at is `unreadable`
    (`<category path>: <message>`).
20. **Names that keep a file in place are compared folded, on every platform**: NFC, then
    `casefold`, for the names of item 10, the patterns of item 11, the stems of item 14, the
    extensions of item 15 and the markers of item 8. A wrong match only keeps a file (or a
    folder) in place; a missed one moves it away from what expects it. Linux mounts file
    systems that ignore case too (FAT, exFAT, NTFS, SMB shares, ext4 `casefold` directories),
    and names made on a Mac arrive decomposed: `Movie.mkv` and `movie.srt` are companions,
    and so are `café.jpg` and `café.xmp` written in two normalizations. Whether a destination
    is taken (item 17), or a version-control directory is there (item 8), is asked of the
    file system, which applies its own rules.

## Categories

21. **The categories are a fixed table, as data** (`organize/categories.toml`); one extension
    has one category, and each has an example in a test. The first table:

    | Category | Extensions |
    |---|---|
    | `Images` | `jpg jpeg png gif webp heic heif bmp tif tiff svg` and camera raw (`cr2 nef arw dng`) |
    | `Videos` | `mp4 mkv avi mov webm m4v wmv mpg mpeg` |
    | `Audio` | `mp3 flac wav ogg oga opus m4a aac wma` |
    | `Documents` | `pdf doc docx odt rtf txt md xls xlsx ods csv ppt pptx odp epub` |
    | `Archives` | `zip rar 7z tar gz tgz bz2 xz zst tar.gz tar.bz2 tar.xz tar.zst iso` |
    | `Installers` | `exe msi dmg pkg deb rpm appimage flatpakref` |

22. **Extensions match regardless of case, the longest first**: `photo.JPG` is `Images`,
    `backup.tar.gz` is `Archives`.
23. **Category directory names are English and fixed in step 5**; naming them in the user's
    language belongs to the UI (step 7).

## Moves and the journal

24. **Tables of their own, schema v4** (audit decision 3; 0011 item 57): `move_batches`, one
    row per `organize move --yes` or `organize undo --yes` (folder, kind `organize` or `undo`,
    state, times, error), and `moves`, one row per file (batch, source, destination, device,
    inode, size, `mtime_ns`, state `pending`, `done`, `rolled_back` or `failed`, and `undoes`,
    the move it reverses). States are constrained by `CHECK`; `operations` is not touched.
25. **Journal before move** (0004 item 1): the batch and every move are committed `pending`
    before the first category directory is made or the first file moves.
26. **Rename only, the destination checked again right before**: one that appeared since the
    check stops the batch (item 27) and is never overwritten; a category directory on another
    device is refused (`cross_device`), never copied into. The window between the last check
    and the rename is the one 0007 accepts.
27. **A batch is all or nothing as far as the disk allows**: what 0004 item 4 calls atomic,
    with the rollback of 0006 item 4. It guarantees that:
    - safeclean overwrites, copies and deletes no file, and never leaves one at both of its
      paths or at neither: one rename moves it (item 26);
    - a move that fails stops the batch: no later move is tried, and the files already moved
      go back newest first, each one tried even when one before it could not go back, and
      never over a file that appeared at its source;
    - the journal says where every file is: `done` at its destination, `rolled_back` at its
      source (the move that failed and those never tried included); where a rename that
      raised, forward or back, left the file is asked of the disk, as recovery asks it (item
      31), not taken from the exception;
    - the batch is `done` only when every move is, `rolled_back` when every file is back at its
      source, and `failed` otherwise: the output names each file left at its destination,
      whose move stays `done` for `organize undo BATCH` (item 29).
    It does not guarantee the folder as it was: a file that cannot go back stays where the
    journal says. A stopped batch exits 3; an exception that is not an `OSError`
    (`KeyboardInterrupt` included) is raised again after the rollback. One raised by the
    rollback itself, or a crash, stops everything: the batch stays `pending`, and what the
    journal already says is true; recovery settles the rest (item 31).
28. **Category directories are made by the batch, after the journal**, with the default mode;
    an existing one is used as it is. They are not rows; they stay after undo (item 4).

## Undo

29. **`organize undo BATCH` moves back what that batch moved**, as a batch of its own (kind
    `undo`) whose moves name what they reverse (`undoes`). Only `done` moves not undone yet
    are taken; an undo batch cannot itself be undone (organize again instead). A batch that
    cannot be undone at all is refused and nothing is planned: `Refused: batch <N>: <reason>`,
    exit 1, the reason one of `organize.undo.UndoReason`, a pinned set: `not_found` (no such
    batch), `undo_batch`, and `pending`, a batch not settled yet, whose files the journal
    cannot place (the command line recovers before it plans, so only a caller of `plan_undo`
    meets it).
30. **What is at the destination goes back if it is a regular file**, even when it changed
    after the move: a document edited after sorting is still the user's document. Preflight
    checks it against the undo plan, as item 19. A missing file stays (`missing`), and so
    does one that cannot be looked at (`missing`, the detail is the system's message); a link
    or a directory stays (`not_regular`); a taken source, or one that cannot be looked at (the
    detail is the system's message), keeps its file sorted (`conflict`) and is never
    overwritten. What stays is named where the batch put it.

## Recovery

31. **`organize.recovery.recover(conn)` settles every move of a pending batch by the disk,
    and moves nothing.** Whatever its journaled state: a move back can have happened after its
    `done` was written. A path holds *the file* when it is a regular file with the journaled
    device, inode, size and `mtime_ns`: a rename keeps all four; a copy, a newcomer, a save by
    replacement, the file edited since or a remount that renumbered it does not. Unlike the
    vault, whose copy wins (0006 item 6), both paths of a move are the user's, and `cp -p` or a
    sync client restoring a file gives another file the same size and `mtime_ns`. A move of
    either kind of batch, with its own source and destination:

    | At the destination | At the source | The move becomes |
    |---|---|---|
    | the file | another file, a link, a directory, or nothing | `done` |
    | another file, a link, a directory, or nothing | the file | `rolled_back` |
    | the file | the file (two hard links) | `failed` |
    | another file, a link, a directory, or nothing | another file, a link, a directory, or nothing | `failed` |

    When both paths are taken by something else, recovery picks neither: it renames,
    overwrites and deletes nothing, and its warning names both paths and what each holds:
    `FAILED: <source> -> <destination>: at the source <what>, at the destination <what>;
    neither was touched`, `<what>` one of `nothing`, `another file`, `a link`, `a directory`
    and `the file`. A `failed` move is never undone
    (item 29 takes `done` moves only); the user decides. Each pending batch then closes `done`
    when every move is `done`, `rolled_back` when every move is `rolled_back`, and `failed`
    otherwise: recovery completes no batch and rolls none back, and its message names the files
    still at their destinations and `safeclean organize undo BATCH`. Each move is settled in a
    transaction of its own and the batch is closed last, so a recovery interrupted or crashed
    anywhere and run again settles the same. It needs no open-file check (as 0011 item 124).
    The message, on stdout: `Recovered <n> interrupted organize batch:` (`batches` for more
    than one), then a line per batch, oldest first, `  [<id>] <state>`. An organize batch
    that left files at their destinations adds
    `: <n> files still sorted; 'safeclean organize undo <id>' moves them back` (`1 file`,
    `moves it back`), then one line `    <destination>` per file; an undo batch that is not
    `done` adds
    `: the undo of batch <B> stopped; 'safeclean organize undo <B>' moves back the files still sorted`.
    Each warning goes to stderr as `safeclean: <warning>`.
32. **Organize is a domain of `pending_domains`** (`Domain.ORGANIZE`, 0011 item 125): its
    pending moves block the quarantine and autostart changes, and theirs block it; the message
    names `safeclean recover` (0011 item 127), which closes the quarantine's work first, then the
    moves, then the autostart changes.

## Command line

33. **`safeclean organize move FOLDER [--yes]`**: without `--yes`, the plan (per category:
    files, size, each `name -> Category/`; then what stays, by reason) and exit 1. With
    `--yes`, the plan is made again inside the lock and carried out; the output lists exactly
    what moved, what was refused and what stays (0010 items 16, 17). On stdout, the plan:

    ```text
    Would move <files>, in <folder>:
      <Category>: <files>
        <name> -> <Category>/
    Stays <n>:
      <reason>: <name>
    Nothing was moved. Re-run with --yes to move these files.
    ```

    and with `--yes`, once the batch is done:

    ```text
    Moved <files>, in <folder> (batch <id>):
      <Category>: <files>
        <name> -> <Category>/
    Refused <n>:
      <reason>: <path>
    Stays <n>:
      <reason>: <name>
    'safeclean organize undo <id>' moves them back
    ```

    `<files>` is `<n> files, <size>` (`1 file`), the size as `scan` writes it; `<folder>` is the
    absolute path. Categories come in table order, each with its files by name; a section with
    nothing in it is left out. What stays is `  <reason>: <name>`, followed by ` (<detail>)`
    when there is one (`  junk: old.tmp (temp-files)`). A refusal is written as the
    quarantine writes one: `  <reason>: <path>`, the path absolute, the reason
    `blocked (<policy reason>)` for `blocked`, followed by ` (<detail>)` when there is one;
    refusals come in the order of the plan. For one file the last line says `moves it back`.
    Otherwise: with nothing to move, `Nothing to move in <folder>.` and what stays; with every
    file refused at move time, `Nothing was moved in <folder>.`, the refusals and what stays,
    and no batch; for a batch that stopped, `Stopped: <error>`, the error that stopped it, and
    the batch's line as recovery writes it (item 31), then the refusals and what stays.
34. **`safeclean organize list`**: the batches, newest first (id, kind, folder, date, files
    moved, state, undone or not). It changes nothing and runs while another domain's work is
    unfinished, as `quarantine list` does. On stdout, `Organize batches: <n>`, then one line
    per batch, its fields two spaces apart:

    ```text
      [<id>] <YYYY-MM-DD HH:MM:SS UTC>  <kind>  <n> files moved  <state>  <folder>
    ```

    The date is when the batch was made; `<kind>` is `organize` or `undo of batch <B>`;
    `<n> files moved` (`1 file moved`) counts its `done` moves; `<state>` is `done`,
    `rolled_back` or `failed`, followed by `, undone` when every file it moved was moved back
    and by `, partly undone` when some were. Without batches: `No organize batches.`
35. **`safeclean organize undo BATCH [--yes]`**: the plan without `--yes` (exit 1), the moves
    back with it. On stdout, as for `move` (item 33), each file named by its path in the
    folder, in journal order:

    ```text
    Would move back <files>, sorted by batch <B> in <folder>:
      <Category>/<name> -> <name>
    Stays <n>:
      <reason>: <Category>/<name>
    Nothing was moved. Re-run with --yes to move these files back.
    ```

    ```text
    Moved back <files>, in <folder> (batch <id>, undoing batch <B>):
      <Category>/<name> -> <name>
    Refused <n>:
      <reason>: <path>
    Stays <n>:
      <reason>: <Category>/<name>
    ```

    `<folder>` is the batch's. Otherwise: with nothing to move back,
    `Nothing to move back from batch <B>.` and what stays; with every file refused,
    `Nothing was moved back from batch <B>.`, the refusals and what stays; a refused batch,
    `Refused: batch <B>: <reason>` (item 29); for a batch that stopped, `Stopped: <error>` and
    the batch's line as recovery writes it (item 31), then the refusals and what stays.
36. **Exit codes as everywhere**: 0 every planned move happened; 1 a preview, nothing to move
    or move back, a refused folder or batch, or a file refused at move time (files that stay
    by the plan are not refusals); 2 usage; 3 a blocker of item 38 (the open-file check's
    included), unfinished work of another domain, a data directory, lock or journal that
    cannot be used, or a batch that stopped (`rolled_back` or `failed`, item 27).

## Platforms

37. **Organize moves files only where nothing blocks it: today Linux, with a reliable
    open-file check.** Wherever a blocker of item 38 applies, `organize move` and
    `organize undo` refuse first, with or without `--yes`: on macOS and Windows always, and on
    Linux when the scan context's open-file check is not reliable (item 39). The refusal comes
    before the journal is opened (the data directory is not created), before planning and
    without asking the open-file check, so not even the plan is shown, as in 0010 item 18.
    This is a conservative limit, kept as a whole while any blocker of the system remains.
    Exit 3; the message names the system, gives one line per blocker in table order and says
    that nothing was changed. On stderr:
    `safeclean: organize does not move files on <system>; nothing was changed`, `<system>`
    one of `Linux`, `macOS` and `Windows`, then `  - <line>` for each blocker, its line of
    item 38; on Linux, the line of `no_open_file_check` alone. `organize list` and
    `safeclean recover` run everywhere, without a reliable open-file check too: neither moves
    a file, and recovery needs no open-file check (item 31).
38. **The blockers are a pinned table, as data** (`organize.platforms.Blocker`, a `StrEnum`,
    each with its one line for the message):

    | Blocker | macOS | Windows | What it would break |
    |---|---|---|---|
    | `no_open_file_check` | yes | yes | item 19: a file a program holds open is moved from under it |
    | `sharing_violations` | | yes | items 27, 29: a move, and the move back, fail halfway through a batch |
    | `path_length_limit` | | yes | item 3: one directory deeper, a path passes 260 characters |
    | `cloud_sync` | yes | yes | 0001 item 4, item 31: moves reach the cloud and other devices; the sync client changes the disk recovery reads |

    The lines of the message, in table order:
    - `no_open_file_check`: `no reliable open-file check: a file a program holds open could be moved from under it`;
    - `sharing_violations`: `a file another program holds open can refuse to move halfway through a batch, and so can the move back`;
    - `path_length_limit`: `one directory deeper, a path can pass the 260-character limit`;
    - `cloud_sync`: `Desktop and Documents can be synced to the cloud: a move would reach every device`.

    Linux has no row of its own. Lifting the refusal on a system needs that system in CI (audit
    B11) and a decision that reviews every blocker of its column; removing a blocker changes
    this table and its test.
39. **`no_open_file_check` comes from the checker, the others from the system, both from the
    scan context.** The checker is `ScanContext.open_files`: a reliable checker on macOS or
    Windows (a fake, in tests) leaves their other blockers, so an open-file backend alone does
    not let organize move there; an unreliable checker blocks Linux too (item 37). The system
    is `ScanContext.platform` (`linux`, `darwin` or `windows`), the system the context was made
    for: a required field with no default, so a context that does not say its system cannot be
    made and none is taken for Linux by omission. `cli.default_context` sets it to the system
    it detects (`detect_platform`); tests make a context for macOS or Windows on any machine.
    The refusal reads neither the machine it runs on nor `sys.platform`. Today only Linux gets
    a reliable checker (`ProcFdChecker`, 0005, which fails closed: a file it cannot check
    counts as open), so from the console the Linux refusal is reached only by a context made
    with an unreliable checker; macOS and Windows get `NoOpenFileCheck` (0004 item 9), so each
    has every blocker of its column.

## Testing

40. **Every item of this decision is cited by a test** as `[0012.N]`. A meta-test fails on an
    item no test cites, on a citation of an item that does not exist, and on an item still
    listed as pending although a test cites it; the pending list starts with every item and
    is empty when step 5 closes. Organize is tested on real temporary trees, like the
    quarantine. A crash is a child process that exits (`os._exit`) at the rename a test
    chooses, before or after it moves, or, for a recovery, right before the statement to the
    journal it chooses: nothing after it runs, so the journal and the disk are what a real
    crash leaves, not what an exception handler would make of them. A recovery is crashed at
    each of its statements in turn, however many it sends.

## Why macOS and Windows are refused

The table of item 38 rests on what follows. None of it can be shown by a test on Linux, so it
is prose; each blocker is lifted by its own decision, with the system in CI (audit B11).
Going from refusal to permission is the safe direction.

**Both systems: no reliable open-file check** (`no_open_file_check`). On Linux, preflight asks
`/proc` whether a process of the user holds the file (0005). Downloads and the Desktop are
where such files live: a torrent client seeding what it downloaded, an editor or Office
autosaving a document by its path, a download manager writing under the final name. Moved
under them, the seeder loses its data and the editor writes a second copy at the old path,
and nothing tells the user which one is current. macOS and Windows have no backend yet:
`NoOpenFileCheck` answers "not open" for everything and says it cannot be trusted. Windows
needs the Restart Manager (`RmStartSession`, `RmRegisterResources`, `RmGetList`, through
`ctypes`), macOS libproc (`proc_listpids`, `proc_pidinfo`, `proc_pidfdinfo`) or `lsof`, each
with its limits decided as 0005 decided those of `/proc`.

**Both systems: folders the system syncs** (`cloud_sync`). Windows moves Desktop, Documents
and Pictures into OneDrive (Known Folder Move), often during setup; macOS offers to keep
Desktop and Documents in iCloud Drive. There a move is a sync operation: it reaches the cloud
and every device of the user, which "local only" (0001 item 4) does not cover; a file can be a
placeholder whose data is elsewhere (Files On-Demand, files evicted by Optimize Mac Storage);
and the sync client renames and restores files by itself, so a disk that disagrees with the
journal (item 31) no longer means a crash, and undo meets files it did not expect. Nothing
tells safeclean yet which folders are synced.

**Windows: sharing violations** (`sharing_violations`). A file that another program opened
without `FILE_SHARE_DELETE`, as most programs open files, cannot be renamed: `os.rename`
raises `PermissionError` (`winerror` 32) in the middle of the batch. The rollback (item 27)
then moves the others back, and a move back can fail the same way: an antivirus, the search
indexer or Explorer's thumbnails open files that have just appeared. The batch ends `failed`
with files left in the category directories; item 27 allows it, Windows would make it
ordinary. A program that does share delete keeps writing to the moved file. A Restart Manager
check before the batch narrows this window, it does not close it: moving on Windows needs
bounded retries and a rule for a move back that keeps failing.

**Windows: path length** (`path_length_limit`). Unless long paths are enabled
(`LongPathsEnabled`), a path has at most 260 characters (`MAX_PATH`), and every move makes it
longer by its category (`Documents\` is ten). Past the limit the move fails and rolls the whole
batch back; with long paths enabled it succeeds and leaves a file that Explorer, Office and
older programs may fail to open. The planner would need a stay reason only Windows has.

**Not blockers.** Names that ignore case (NTFS, APFS, HFS+) or Unicode normalization (APFS,
HFS+) are handled on every platform by item 20. `desktop.ini` and `Thumbs.db` stay by item 10.
`os.rename` on Windows refuses a taken destination instead of replacing it: the check of item
26 stays, and the race 0007 accepts gets narrower. macOS privacy protection (TCC) denies a
terminal Desktop, Documents and Downloads until the user allows it: listing fails, and the
folder is refused as an unreadable one is on Linux (item 7). That this code has never run on
either system is not a blocker by itself, since the autostart changes run there untested
(0011, B11); the refusal stays all the same, and CI on that system is what lifting it starts
with (item 38).

**Why not the plan alone.** A plan is what `--yes` carries out (0010): on these systems it
would list moves the batch can fail to make (sharing violations, path length) and keep none
of the files an open-file check would keep. Showing it with a warning would be a separate
decision, as in 0010 item 18.

**What would lift them**: `no_open_file_check`, a backend and its decision;
`sharing_violations`, that backend before the batch, bounded retries and a rule for a failing
move back; `path_length_limit`, a stay reason computed at the system's limit; `cloud_sync`,
knowing the synced folders (OneDrive's and iCloud Drive's roots) and refusing them as item 8
refuses a game library, which would leave the other folders to sort.

## Amendments

- **0002, section 3**: moves follow the quarantine's rules, not its service (audit B6): the
  same journal before the move, preflight, rename only, atomic batch and recovery by the disk,
  in a service and tables of their own; `QuarantineService` is bound to its vault.
- **0004, consequences**: organize reuses preflight and the rules of the journal and the
  rollback, not the quarantine's tables; preflight gains one reason, `conflict`, which only
  organize gives (item 19).

## Step 5 plan

Each line is one commit or one test/fix pair; every red test is approved before it is
committed.

1. The meta-test, every item pending (item 40).
2. Refactor: preflight leaves the quarantine for a module both domains use
   (`core.preflight`); behaviour unchanged.
3. Schema v4, moves with device and inode, and `Domain.ORGANIZE` (items 24, 32).
4. The category table (items 21-23).
5. The platform table, `organize.platforms` (items 38, 39).
6. The planner, read-only: the folder (7, 8), what stays (9-18), folded names (20: the
   `Movie.mkv` and `movie.srt` pair, names in two Unicode normalizations), determinism (5, 6).
7. The mover: journal, preflight, rename, all or nothing, directories (19, 25-28); a rename
   that fails before or after it moves, forward and back; a partial rollback; a newcomer at a
   source; a taken destination; an interrupt.
8. Recovery by the file's identity, and `safeclean recover` with it (31, 32): crashes before
   and after a rename and during the rollback, a recovery interrupted, or crashed at each of
   its statements, and run again, a device or inode changed by a remount, both paths taken by
   something else, the file at both.
9. Undo (29, 30).
10. The CLI: `organize move | list | undo` (1-4, 33-36), and on macOS and Windows, and on
    Linux with an unreliable open-file check, `move`, `move --yes`, `undo` and `undo --yes`
    refused before anything while `list` and `recover` run (37); `ScanContext.platform`,
    required, set by `cli.default_context` (39).
11. README and roadmap; the pending list is empty.

## Accepted limitations

- **One level only**: files in subdirectories are not sorted; a folder nested in a mess stays
  as it is.
- **A taken name is not renamed**: the file stays; numbered names are a later decision.
- **Empty category directories stay after undo**: removing them would need a second deletion
  point (0008).
- **The plan and `--yes` are two passes**, as for `quarantine add --from-analysis` (0010).
- **The table is fixed and English**: no user categories or rules in step 5.
- **Dependencies are recognized by markers and names only**: a script that opens a file
  beside it by a relative path cannot be seen; one level, companions and undo are the
  answer, not a promise.
- **Linux only** until the blockers of item 38 are lifted, each by its own decision.
- **Device and inode numbers that change on remount** (a USB disk plugged in again, FAT,
  some SMB mounts): recovery after the remount finds the file at neither path and marks its
  move `failed`; nothing is moved, and the warning names both paths.
- **Sync clients on Linux** (Dropbox, Nextcloud, ...): a folder one of them watches is sorted
  like any other and the moves are synced; no system folder is synced by default there, and
  the user chose the folder. Knowing synced folders is the work `cloud_sync` needs anyway.
