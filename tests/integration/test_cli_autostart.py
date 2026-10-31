"""`safeclean autostart list`: end-to-end on real temporary trees and a fake registry.

Report only: nothing is created, changed or deleted, the scan context is never built, and the
registry is read only on Windows. Entries are grouped by source in reader order; machine-wide
entries on Windows need ``--include-machine``, and the report says when they were not read.
"""

import io
import json
from pathlib import Path

import pytest

from fakes import FakeRegistry
from safeclean import cli
from safeclean.autostart.listing import AutostartContext
from safeclean.autostart.registry import Hive, Registry, RegValue, ValueKind
from safeclean.autostart.run_keys import RUN
from safeclean.core.heuristics import Platform
from safeclean.core.scanner import ScanContext

APP = "[Desktop Entry]\nType=Application\nName=App\nExec=/usr/bin/app --tray\n"
HINT = (
    "Note: machine-wide entries (HKLM, services, scheduled tasks, the common startup folder)"
    " were not read; add --include-machine to read them."
)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def no_scan_context() -> ScanContext:
    raise AssertionError("autostart list needs no scan context")


def no_registry() -> Registry:
    raise AssertionError("the registry is only for Windows")


def context(
    platform: Platform, tmp_path: Path, registry: Registry | None = None
) -> AutostartContext:
    env = {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CONFIG_DIRS": str(tmp_path / "etc" / "xdg"),
    }
    factory = no_registry if registry is None else lambda: registry
    return AutostartContext(platform, env, home=tmp_path, root=tmp_path, registry=factory)


def run(args: list[str], autostart: AutostartContext) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(
        args, out=out, context_factory=no_scan_context, autostart_context=lambda: autostart
    )
    return code, out.getvalue()


@pytest.fixture
def linux(tmp_path: Path) -> AutostartContext:
    system = tmp_path / "etc" / "xdg" / "autostart"
    write(system / "app.desktop", APP)
    write(tmp_path / "config" / "autostart" / "app.desktop", APP + "OnlyShowIn=GNOME;\n")
    write(system / "tray.desktop", APP.replace("Name=App", "Name=Tray") + "Hidden=true\n")
    write(system / "broken.desktop", "not an entry\n")
    return context("linux", tmp_path)


def snapshot(root: Path) -> list[tuple[str, bytes]]:
    return sorted((str(p), p.read_bytes()) for p in root.rglob("*") if p.is_file())


# --- text ----------------------------------------------------------------------------------------


def test_text_report_groups_entries_by_source(tmp_path: Path, linux: AutostartContext) -> None:
    user = tmp_path / "config" / "autostart" / "app.desktop"
    system = tmp_path / "etc" / "xdg" / "autostart"

    code, out = run(["autostart", "list"], linux)

    assert code == 0
    assert out == (
        "safeclean autostart list - report only, nothing was changed\n"
        "Entries: 2, 1 disabled\n"
        "\n"
        "XDG autostart: 2\n"
        "  app  [enabled, user]\n"
        "    command: /usr/bin/app --tray\n"
        f"    location: {user}\n"
        f"    shadows: {system / 'app.desktop'}\n"
        "    note: OnlyShowIn=GNOME;\n"
        "  tray  [disabled, system]\n"
        "    command: /usr/bin/app --tray\n"
        f"    location: {system / 'tray.desktop'}\n"
        "\n"
        "Skipped: 1\n"
        f"  xdg_autostart: {system / 'broken.desktop'} (no [Desktop Entry] group)\n"
    )


def test_an_empty_system_is_an_empty_report(tmp_path: Path) -> None:
    code, out = run(["autostart", "list"], context("linux", tmp_path))

    assert code == 0
    assert out == (
        "safeclean autostart list - report only, nothing was changed\n"
        "Entries: 0, 0 disabled\n"
        "\n"
        "Skipped: 0\n"
    )


def test_listing_changes_nothing(tmp_path: Path, linux: AutostartContext) -> None:
    before = snapshot(tmp_path)

    run(["autostart", "list"], linux)
    run(["autostart", "list", "--json"], linux)

    assert snapshot(tmp_path) == before


# --- Windows and consent -------------------------------------------------------------------------


def test_windows_without_consent_says_what_was_not_read(tmp_path: Path) -> None:
    registry = FakeRegistry({(Hive.HKCU, RUN): [RegValue("Sync", ValueKind.REG_SZ, "sync.exe")]})

    _, out = run(["autostart", "list"], context("windows", tmp_path, registry))

    assert out.splitlines()[1:4] == ["Entries: 1, 0 disabled", HINT, ""]
    assert "Run keys: 1\n  Sync  [enabled, user]\n    command: sync.exe\n" in out
    assert Hive.HKLM not in {hive for hive, _ in registry.reads}


def test_windows_with_consent_reads_the_machine_too(tmp_path: Path) -> None:
    value = RegValue("Agent", ValueKind.REG_SZ, "agent.exe")
    registry = FakeRegistry({(Hive.HKLM, RUN): [value]})

    _, out = run(["autostart", "list", "--include-machine"], context("windows", tmp_path, registry))

    assert HINT not in out
    assert "  Agent  [enabled, system]\n" in out


def test_other_systems_have_no_machine_scope_to_consent_to(linux: AutostartContext) -> None:
    _, without = run(["autostart", "list"], linux)
    _, with_flag = run(["autostart", "list", "--include-machine"], linux)

    assert HINT not in without
    assert with_flag == without


# --- JSON ----------------------------------------------------------------------------------------


def test_json_lists_every_field(tmp_path: Path, linux: AutostartContext) -> None:
    user = tmp_path / "config" / "autostart" / "app.desktop"
    system = tmp_path / "etc" / "xdg" / "autostart"

    code, out = run(["autostart", "list", "--json"], linux)
    data = json.loads(out)

    assert code == 0
    assert data["platform"] == "linux"
    assert data["include_machine"] is False
    assert data["items"][0] == {
        "source": "xdg_autostart",
        "scope": "user",
        "name": "app",
        "command": "/usr/bin/app --tray",
        "location": str(user),
        "enabled": True,
        "digest": data["items"][0]["digest"],
        "shadows": str(system / "app.desktop"),
        "notes": ["OnlyShowIn=GNOME;"],
    }
    assert len(data["items"][0]["digest"]) == 32
    assert [(i["name"], i["enabled"], i["shadows"]) for i in data["items"]] == [
        ("app", True, str(system / "app.desktop")),
        ("tray", False, None),
    ]
    assert data["skipped"] == [
        {
            "source": "xdg_autostart",
            "location": str(system / "broken.desktop"),
            "detail": "no [Desktop Entry] group",
        }
    ]


def test_json_records_the_consent(tmp_path: Path) -> None:
    ctx = context("windows", tmp_path, FakeRegistry({}))

    _, out = run(["autostart", "list", "--json", "--include-machine"], ctx)

    assert json.loads(out) == {
        "platform": "windows",
        "include_machine": True,
        "items": [],
        "skipped": [],
    }


def test_without_a_context_the_detected_platform_is_listed(
    linux: AutostartContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    platforms: list[Platform] = []

    def live(platform: Platform) -> AutostartContext:
        platforms.append(platform)
        return linux  # never the live system in a test

    monkeypatch.setattr(cli, "default_autostart_context", live)
    out = io.StringIO()

    assert cli.main(["autostart", "list"], out=out, context_factory=no_scan_context) == 0
    assert platforms == [cli.detect_platform()]
    assert "  app  [enabled, user]\n" in out.getvalue()


# --- usage ---------------------------------------------------------------------------------------


def test_autostart_needs_an_action(
    linux: AutostartContext, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(["autostart"], linux)

    assert exc.value.code == 2
    assert "list" in capsys.readouterr().err
