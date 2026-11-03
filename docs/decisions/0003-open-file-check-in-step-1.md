# 0003. No open-file backend in step 1; reports disclose it, actions must refuse

- Status: accepted
- Date: 2026-10-31

## Context

The policy blocks open files through the `OpenFileChecker` protocol, but step 1 has no
OS-specific backend (Windows handles, `/proc/*/fd`, `lsof`). Step 1 is report-only.

## Decision

- `kresorter scan` uses `NoOpenFileCheck` (reports nothing as open) and sets
  `ScanContext.open_files_checked = False`.
- The text report prints a note and the JSON report has `"open_file_check": false`.
- **Any action** (quarantine, deletion, organizer move: step 2 and later) must refuse to run
  without a real checker, and must re-check open state and size/mtime right before acting.

## Consequences

- Step 1 output may list files that are currently open; this is disclosed and harmless because
  nothing is acted on.
- Step 2 must add a real backend per platform (or refuse) before the first quarantine move.
