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
