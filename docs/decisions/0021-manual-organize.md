# 0021. Shortcuts and manual organization

- Status: in progress
- Builds on: 0012, 0018, 0020

## Agreed direction

Manual organization will let people create groups and assign files, shortcuts and whole folders
without entering or rearranging the contents of those folders. Local AI is optional: it may suggest
groups, which the user can edit or disregard. No proposed moves happen until the user reviews and
confirms them. Moving a folder can break paths used by projects or programs; warn prominently
before confirmation. No overwrite; journal and undo with clear reporting of anything not restored.
This requires new safety, recovery and undo work for directories: the existing file preflight,
identity and undo rules do not support them. Directory moves are not yet implemented.

The manual file interface provides selectable and searchable tiles, named groups, drag-and-drop
and a keyboard-accessible assignment button. Optional local AI proposes editable assignments
without replacing the user's own. Preview is read-only, then confirmation precedes a journaled
batch with existing preflight and undo; changed or missing entries are not moved. Protected
entries stay protected, and unassigned companions stay beside a file. This first version is for
files only; directory moving and its warning remain pending.

## Shortcuts

The standard kind-based organizer proposes these regular files in `Shortcuts`. The existing
preview and confirmation apply. In the UI, confirmation warns that some shortcuts may stop working,
especially if they use relative paths. Symlinks and other non-regular entries remain untouched.

| Category | Extensions |
| --- | --- |
| `Shortcuts` | `lnk`, `url` |

## Manual organizer: implementation requirements

- Work on one explicitly selected, policy-approved folder. Show its immediate children as
  selectable cards with a search field and a compact view; provide a group area with group
  creation, multi-selection and drag-and-drop. Group assignment changes only an in-memory plan.
- Offer AI as an optional action, never automatic. Show suggestions as editable assignments;
  the user can ignore them. Only names needed for grouping go to the configured local model,
  not file contents or paths. Never execute model output without validation and confirmation.
- Review lists each source and destination, including whole directories and new group folders.
  Ask for confirmation before disk changes; make the warning about potentially broken paths
  prominent whenever a folder moves. A warning does not guarantee applications still work.
- Directory actions need their own preflight: real directories only, no symbolic links, Windows
  reparse points, mount points or policy-blocked paths; reject source/target overlap, cycles,
  duplicate assignments and collisions. Revalidate identities, paths and permissions at execution.
  Do not treat a directory's metadata as a reliable fingerprint of its whole tree. Account for
  nested mounts, protected objects and open files before making claims about safe moves.
- Extend journal, recovery and undo explicitly for directories, including identity checks and
  conservative handling of changed or replaced items. Do not overwrite a destination or a
  newcomer at the original location. Report failures and partial recovery accurately. A directory
  must never be moved by bypassing the regular-file checks of the current mover.
- Cover unsafe paths, stale plans, conflicts, interrupted batches and undo in tests on Linux and
  Windows before exposing directory moves. Interface work also needs tests for the optional AI,
  manual changes, cancellation and warning.
