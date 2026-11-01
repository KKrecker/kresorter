# safeclean

Cross-platform desktop app for **safe** cleanup and triage of files on your PC.
Open source, local-only, no telemetry.

> Status: early development, console mode only. Steps 1-4 are done (scanner; quarantine and
> journal; analysis; autostart); step 5, the file organizer, is next
> ([roadmap](docs/roadmap.md)).

## Safety principles

- **Report first.** Nothing is deleted automatically: full report → quarantine → delete only after confirmation.
- **Everything is reversible.** Every action is journaled before it happens and can be rolled back.
- **No direct deletion.** All removal goes through the quarantine API; `os.remove`, `shutil.rmtree`
  and friends are banned in code *and* tests (enforced by ruff and a test).
- **Safe zones by default.** Program Files, user profiles and open files are blacklisted.
- **Local only.** No telemetry; the optional LLM (Ollama) runs locally.

## Usage (console)

### Reports: `scan`, `analyze`

```bash
safeclean scan                 # default safe zones: ~/.cache and ~/Downloads
safeclean scan ~/Projects /tmp # explicit roots (Temp only when chosen explicitly)
safeclean scan --json --no-hash ~/Downloads
safeclean analyze              # a safety level and the reasons for each finding
safeclean analyze --json --large 1024 --older-than 365 ~/Downloads
```

Neither changes the disk, not even safeclean's data directory. `scan` lists junk candidates,
duplicate groups and everything it skipped, with the reason. `analyze` rates each finding
`safe`, `likely_safe` or `review` and says why; which copy of a duplicate group stays is
decided for you and that copy is never proposed. Large (`--large`, MiB) and old (`--older-than`,
days unmodified) files are listed for review only.

### Quarantine

```bash
safeclean quarantine add ~/Downloads/old.iso   # move aside (reversible)
safeclean quarantine add --from-analysis --level safe        # show what would move
safeclean quarantine add --from-analysis --level safe --yes  # move it
safeclean quarantine list                      # ids, original paths, sizes
safeclean quarantine restore 3                 # put back; never overwrites
safeclean quarantine purge 3                   # show what would be deleted; deletes nothing
safeclean quarantine purge --yes 3             # permanently delete the vault copy
```

Every file is checked again right before it moves. `--from-analysis` takes `safe` findings, or
`safe` and `likely_safe` with `--level likely_safe`; `review` is never moved in bulk. The
quarantine needs a reliable open-file check: Linux has one; on macOS and Windows these commands
refuse (exit code 3) until their backends exist.

### Autostart

```bash
safeclean autostart list                      # every entry with its id; report only
safeclean autostart list --json --include-machine  # Windows: also HKLM, services, tasks
safeclean autostart disable 3f2a9c0d1b7e      # show what would be written
safeclean autostart disable 3f2a9c0d1b7e --yes
safeclean autostart enable 81d4e0a6c2f9 --yes # the id from a new 'list'
```

`list` shows each entry's id; any unique beginning of it is enough, and an entry that changed
since it was listed has another one. Two sources can be changed: XDG autostart entries on Linux
and `HKCU` Run values on Windows; every other source is listed, never written. Nothing is ever
deleted: your own entry is replaced by a copy with `Hidden=true` and the original is kept; a
system entry is shadowed by a stub in your autostart directory, `/etc` is never written; a Run
value gets the `StartupApproved` flag the Task Manager writes, the value itself is never
touched. `enable` puts back only what safeclean changed.

### Recovery

```bash
safeclean recover   # close interrupted work of every kind; `autostart recover` is the same
```

The commands that act (`quarantine`, `autostart disable|enable`, `recover`) share one journal
in one data directory, and only one of them runs at a time. The data directory is
`$XDG_DATA_HOME/safeclean` (by default `~/.local/share/safeclean`) on Linux,
`~/Library/Application Support/safeclean` on macOS and `%LOCALAPPDATA%\safeclean` on Windows;
safeclean refuses to use one inside a scan zone. Each command first closes its own interrupted
work; if work of another kind is left, it changes nothing and names `safeclean recover`.
Recovery decides by what is on the disk or in the registry, never redoing or undoing anything.
`safeclean recover` needs no open-file check, so it also runs where the quarantine cannot act.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | done; reports always end with 0 |
| 1 | something was refused, rolled back or not confirmed (a preview), or there was nothing to do |
| 2 | usage error |
| 3 | cannot act safely here: no reliable open-file check, unfinished work of another kind, a data directory, lock or journal that cannot be used, or a change that failed or cannot be checked |

`scan`, `analyze` and `autostart list` exit with 0 or 2; `recover` with 0, 2 or 3.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy && pytest
```

Python 3.11 to 3.14. `pytest` fails below 100 % line and branch coverage.

Decisions are logged in [`docs/decisions/`](docs/decisions/); the plan is in [`docs/roadmap.md`](docs/roadmap.md).

## License

MIT
