# 0016. Windows open-file check: an exclusive open, then the quarantine on Windows

- Status: accepted
- Date: 2026-11-03
- Builds on: 0003, 0004 (items 3-5, 9), 0005, 0012 (item 37), 0015
- Amends: 0004 item 9 and 0005 (Windows gets a reliable backend, an exclusive open rather than
  the Restart Manager), 0004 item 3 (the quarantine renames with `Path.rename`, which on
  Windows never replaces a file)

## Context

The quarantine refuses to start without an open-file check it can trust (0004 item 5), and
Windows has none (0004 item 9, 0005): the Windows application of 0015 would only report.

0004 item 9 named the Restart Manager. It answers which processes use a file, for installers
that close and restart them: a session per question, the files registered with it, and only
the processes it can name. Windows has a more direct answer in share modes. While any handle
reads, writes or deletes a file, a new open with share mode 0 is refused with
`ERROR_SHARING_VIOLATION`; the kernel checks it on the file itself, for every process and
every user, through every hard link. An open with read access and share mode 0, closed at
once, asks the question without keeping a lock. Python's own `open()` shares reading and
writing but not exclusivity, so a test holds a file open as any program does.

What it misses: a handle opened for attributes only (it has no data access, and moving the
file does not disturb it), and a file mapped into memory whose handle was closed (in practice a
program that maps a file keeps its handle). The `/proc` check of Linux misses other users'
processes; this one does not. What it costs: for the instant between its two calls, another
program opening the file is refused; and an antivirus that has just opened a file makes the
check say "open", so the file is refused and can be quarantined later.

Windows renames differently. `os.replace`, the quarantine's rename (0004 item 3), replaces a
file at the destination on both systems; `os.rename` replaces it on Linux (the same
`rename(2)`) but never on Windows, where it fails with `FileExistsError`. With `Path.rename`
the race the quarantine accepts on Linux (a file appearing at the destination between the
check and the rename) is closed on Windows. A file another program opens without sharing
deletion, between the check and the rename, makes the rename fail; for the quarantine that
rolls the batch back (0004 item 4). Organize's other blockers on Windows are reviewed by 0017;
this decision lifts only the open-file one.

Every numbered item below is a behaviour a test can show, and is cited by one (item 12). What
only Windows can show runs on CI's Windows job (0015 item 20); this machine runs Linux and
checks the same code through fakes.

## The check

1. **An exclusive open.** `core.open_files.windows.ShareModeChecker` (`reliable=True`) calls
   `CreateFileW(path, GENERIC_READ, 0, NULL, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT |
   FILE_FLAG_OPEN_NO_RECALL, NULL)` and `CloseHandle` on the handle at once: a handle is "not
   open", `ERROR_SHARING_VIOLATION` (32) is "open".
2. **Fail closed.** Any other error raises `OpenFileCheckError` with the Windows error's code
   and message, which the policy treats as open (0005); a failing `CloseHandle` raises it
   too.
3. **A question, not a lock.** The check reads no byte, asks for no write or delete access,
   holds its handle only between the two calls (nothing is done in between), does not follow
   a reparse point (`FILE_FLAG_OPEN_REPARSE_POINT`) and does not download a file kept in the
   cloud (`FILE_FLAG_OPEN_NO_RECALL`).
4. **Long paths.** The path is made absolute and given with `\\?\` (`\\?\UNC\` for a share),
   so a path over 260 characters is checked like any other.
5. **Windows gets it.** `checker_for_platform` returns `ShareModeChecker` for Windows, named
   `windows` (the system a scan context is made for) or `win32` (`sys.platform`); macOS and
   every system other than Linux still get `NoOpenFileCheck`. A scan on Windows reports
   `"open_file_check": true`, and Overview's note about an unreliable check is not shown
   there. The check is the running system's: a scan context made for another system (as the
   tests make) has `NoOpenFileCheck`.
6. **Testable everywhere.** The checker takes the calls it needs (`CreateFileW`,
   `CloseHandle`, the last error and its message) as a protocol, `Kernel`; the default,
   `Kernel32`, is `ctypes.WinDLL("kernel32", use_last_error=True)` with the functions' types
   (a handle as a signed integer, so that `INVALID_HANDLE_VALUE` is -1), loaded when the
   checker is made. Tests on every system give a fake that records each call's arguments and
   answers a handle or an error, so every line is covered on Linux and on Windows; the live
   tests of item 7 add checks, not lines.
7. **Live on Windows** (skipped elsewhere): a file this process holds open with `open()` is
   open, and so is a file a child process holds; once it is closed, it is not; a hard link to
   an open file is open; a missing file raises `OpenFileCheckError`; after a check the file has
   the same size and `mtime_ns`, and another `open()` succeeds at once.

## The quarantine on Windows

8. **A rename never replaces.** The quarantine moves with `Path.rename` instead of
   `Path.replace`: into the vault, back in a rollback, back in a restore. On Windows a file that
   reaches the destination after the check makes the rename fail with `FileExistsError`, and it
   is never overwritten: a restore refuses the item as `conflict`, a rollback keeps it in the
   vault (`failed`, restorable later). Only the rename's own refusal is a conflict: a parent
   that cannot be created stays `move_failed`, and a parent that became a file no longer
   breaks the restore. On Linux `rename(2)` is what ran before, and the check right before the
   move stays the guard (the race window of `quarantine.service`).
9. **Live on Windows** (skipped elsewhere), in a temporary profile: `kresorter quarantine
   --from-analysis --yes` moves the safe findings of a made-up tree into the vault,
   `kresorter quarantine restore` puts them back with their `mtime_ns`, and `kresorter
   quarantine purge` deletes the vault's copies; a file a child process holds open is refused
   `open_file`; where the runner has a second drive, a file on it is refused `cross_device`.
10. **Organize's open-file blocker is lifted on Windows**: with `ShareModeChecker`, the
    blockers of Windows no longer include `no_open_file_check` (0012 item 39), and its line
    leaves organize's refusal there; the other blockers of its column are 0017's to lift.
11. **The README**: the quarantine needs a reliable open-file check, which Linux and Windows
    have, and on macOS the commands refuse; what the Windows check cannot see, in one
    sentence.

## The meta-test

12. **Every item of this decision is cited by a test** as `[0016.N]`. A meta-test fails on an
    item no test cites, on a citation of an item that does not exist, and on an item still
    listed as pending although a test cites it; the pending list starts with every item and is
    empty after the last commit of this decision's plan. The meta-test checks the rules of
    `tests/support/decisions.py` on made-up items and citations, and that check cites this
    item.

## Plan (line 9 of the step 8 plan of 0015)

Each line is one commit or one test/fix pair (red, then green). The items in brackets leave
the pending list in that commit, and no earlier test cites them.

1. The meta-test, every other item pending [12].
2. `ShareModeChecker` through a fake kernel: the open, failing closed, the flags, long paths
   [1-4, 6].
3. `checker_for_platform` on Windows, the scan's report and Overview's note; organize's
   refusal without the open-file line [5, 10].
4. The quarantine renames with `Path.rename` [8].
5. The live tests, run by CI's Windows job once the repository is on GitHub [7, 9].
6. The README [11].

## Accepted limitations

- **Not seen**: a handle for attributes only, and a file mapped into memory after its handle
  was closed.
- **An instant of exclusivity**: a program that opens the file during the check is refused
  once; an antivirus that holds the file makes it "open" for a while.
- **One drive**: a file on another drive than the data directory is refused (`cross_device`),
  as across file systems on Linux.

## The owner's answers

- Accepted as proposed (2026-11-03); organize is wanted on Windows too, which 0017 decides.
