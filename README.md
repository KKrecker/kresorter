# safeclean

Cross-platform desktop app for **safe** cleanup and triage of files on your PC.
Open source, local-only, no telemetry.

> Status: early development (step 1: scanner core, console mode).

## Safety principles

- **Report first.** Nothing is deleted automatically: full report → quarantine → delete only after confirmation.
- **Everything is reversible.** Every action is journaled and can be rolled back.
- **No direct deletion.** All removal goes through the quarantine API; `os.remove`, `shutil.rmtree`
  and friends are banned in code *and* tests (enforced by ruff and a test).
- **Safe zones by default.** Program Files, user profiles and open files are blacklisted.
- **Local only.** No telemetry; the optional LLM (Ollama) runs locally.

## Usage (step 1: console, report only)

```bash
safeclean scan                 # default safe zones: ~/.cache and ~/Downloads
safeclean scan ~/Projects /tmp # explicit roots (Temp only when chosen explicitly)
safeclean scan --json --no-hash ~/Downloads
```

`scan` never changes the disk. It lists junk candidates, duplicate groups and everything it
skipped, with the reason.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy && pytest
```

Decisions are logged in [`docs/decisions/`](docs/decisions/); the plan is in [`docs/roadmap.md`](docs/roadmap.md).

## License

MIT
