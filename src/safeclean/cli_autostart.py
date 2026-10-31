"""``safeclean autostart list``: every autostart entry of this system; report only (0011).

Entries are grouped by source in reader order. On Windows, machine-wide entries are read only
with ``--include-machine``, and the report says when they were not. Nothing is created,
changed or deleted.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, TextIO

from safeclean.autostart.listing import AutostartContext, list_autostart
from safeclean.autostart.models import AutostartItem, AutostartListing, AutostartSkipped, Source

MACHINE_NOTE = (
    "Note: machine-wide entries (HKLM, services, scheduled tasks, the common startup folder)"
    " were not read; add --include-machine to read them."
)

_TITLES = {
    Source.XDG_AUTOSTART: "XDG autostart",
    Source.SYSTEMD_USER: "systemd user units",
    Source.RUN_KEY: "Run keys",
    Source.RUN_ONCE_KEY: "RunOnce keys",
    Source.STARTUP_FOLDER: "Startup folders",
    Source.SERVICE: "Services",
    Source.SCHEDULED_TASK: "Scheduled tasks",
    Source.LAUNCH_AGENT: "launchd",
}


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    autostart = commands.add_parser("autostart", help="programs that start on their own")
    actions = autostart.add_subparsers(dest="action", required=True)
    list_cmd = actions.add_parser("list", help="list autostart entries; report only")
    list_cmd.add_argument("--json", action="store_true", help="machine-readable output")
    list_cmd.add_argument(
        "--include-machine",
        action="store_true",
        help="Windows: also read HKLM, services, scheduled tasks and the common startup folder",
    )


def run(args: argparse.Namespace, context: AutostartContext, out: TextIO) -> int:
    listing = list_autostart(context, include_machine=args.include_machine)
    if args.json:
        out.write(render_json(listing, context, include_machine=args.include_machine))
    else:
        note = context.platform == "windows" and not args.include_machine
        out.write(render_text(listing, machine_note=note))
    return 0


def render_text(listing: AutostartListing, *, machine_note: bool) -> str:
    disabled = sum(not item.enabled for item in listing.items)
    lines = [
        "safeclean autostart list - report only, nothing was changed",
        f"Entries: {len(listing.items)}, {disabled} disabled",
    ]
    if machine_note:
        lines.append(MACHINE_NOTE)
    by_source: dict[Source, list[AutostartItem]] = {}
    for item in listing.items:
        by_source.setdefault(item.source, []).append(item)
    for source, items in by_source.items():
        lines += ["", f"{_TITLES[source]}: {len(items)}"]
        lines += [line for item in items for line in _item_lines(item)]
    lines += ["", f"Skipped: {len(listing.skipped)}"]
    lines += [f"  {s.source}: {s.location} ({s.detail})" for s in listing.skipped]
    return "\n".join(lines) + "\n"


def _item_lines(item: AutostartItem) -> list[str]:
    state = "enabled" if item.enabled else "disabled"
    lines = [
        f"  {item.name}  [{state}, {item.scope}]",
        f"    command: {item.command}",
        f"    location: {item.location}",
    ]
    if item.shadows is not None:
        lines.append(f"    shadows: {item.shadows}")
    return lines + [f"    note: {note}" for note in item.notes]


def render_json(
    listing: AutostartListing, context: AutostartContext, *, include_machine: bool
) -> str:
    data: dict[str, Any] = {
        "platform": context.platform,
        "include_machine": include_machine,
        "items": [_item_json(item) for item in listing.items],
        "skipped": [_skip_json(skip) for skip in listing.skipped],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _item_json(item: AutostartItem) -> dict[str, Any]:
    return {
        "source": str(item.source),
        "scope": str(item.scope),
        "name": item.name,
        "command": item.command,
        "location": item.location,
        "enabled": item.enabled,
        "digest": item.digest,
        "shadows": item.shadows,
        "notes": list(item.notes),
    }


def _skip_json(skip: AutostartSkipped) -> dict[str, Any]:
    return {"source": str(skip.source), "location": skip.location, "detail": skip.detail}
