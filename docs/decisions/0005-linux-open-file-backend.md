# 0005. Linux open-file backend via /proc and its limitation

- Status: accepted
- Date: 2026-10-31
- Builds on: 0003 (open-file check before any action), 0004 items 5 and 9

## Context

The quarantine refuses to start without an open-file checker with `reliable=True`. Step 2 ships
the Linux backend only. Without root, `/proc/<pid>/fd` of other users' processes (including
`/proc/1/fd`) is not readable.

## Decision

- `core.open_files` becomes a package: `base` (protocol with `reliable`, `NoOpenFileCheck`,
  `OpenFileCheckError`), `linux` (`ProcFdChecker`), `checker_for_platform()`.
- `ProcFdChecker` compares `(st_dev, st_ino)` of the target (`lstat`) with every
  `/proc/<pid>/fd/<n>` it can read, so hard links count as the same file. Non-pid entries and
  pseudo fds (sockets, pipes, anon inodes) are ignored.
- Processes that exit during the scan, or whose `fd` directory raises `PermissionError`, are
  **skipped**. Treating them as "open" would make every file look open for a normal user.
- Fail closed: a missing `/proc` or target raises `OpenFileCheckError` (an `OSError`); any other
  unexpected `OSError` propagates. `PathPolicy.check_file` treats both as "open".
- `checker_for_platform`: Linux gets `ProcFdChecker` (`reliable=True`); every other platform gets
  `NoOpenFileCheck` (`reliable=False`), so the quarantine refuses politely there.

## Consequences

- **Known limitation:** a file held open only by another user's process is not detected. For
  files in the user's own home this is rare; preflight's size/`mtime_ns` re-check and
  restore-from-quarantine remain the safety net. Documented here and in the module docstring.
- Running as root removes the limitation (all fds readable).
- Windows (Restart Manager) and macOS (`lsof`) backends come with those OSes in CI.
