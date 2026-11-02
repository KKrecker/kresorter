"""``safeclean llm status`` and ``--explain``, end to end (decision 0013).

Ollama is the scripted server of ``support.ollama``, on loopback; a script is in the order of
the requests: ``version``, ``tags``, then one ``generate`` per subject. The commands run on real
temporary trees: ``analyze`` over ``zone``, ``autostart list`` over XDG entries in ``tmp_path``
and ``organize move`` (its plan: ``--explain`` is never given with ``--yes``) over a folder in
``zone``. The settings are the environment given to ``cli.main``.
"""

import io
import json
import os
import re
import socket
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import pytest

from fakes import FakeRegistry
from safeclean import cli
from safeclean.autostart.listing import AutostartContext
from safeclean.autostart.registry import Hive, RegValue, ValueKind
from safeclean.autostart.run_keys import RUN, RUN_ONCE
from safeclean.core.scanner import ScanContext
from safeclean.environment import Environment
from safeclean.llm.settings import Address
from safeclean.llm.transport import LIMITS, Limits
from support.cli import autostart_context, scan_context
from support.files import snapshot, write
from support.journal import query
from support.ollama import Answer, ScriptedOllama, after, as_json, head, redirect

VERSION = as_json({"version": "0.6.2"})
TAGS = as_json({"models": [{"name": "llama3.2:latest"}, {"name": "qwen2.5:7b"}]})
NO_MODELS = as_json({"models": []})
_LATE = b'{"version": "0.6.2"}'
LATE_VERSION = after(1.0, head(200, length=len(_LATE)) + _LATE)  # in time only without QUICK
CHECKS = [("GET", "/api/version"), ("GET", "/api/tags")]
GENERATE = ("POST", "/api/generate")
QUICK = Limits(check_seconds=0.3, generate_seconds=0.3)
DAY_NS = 86_400 * 10**9
HEADER = (
    "AI explanations (llama3.2 via Ollama; advisory, may be wrong; nothing above depends on them):"
)
UNAVAILABLE = re.compile(
    r"AI explanations unavailable: (?P<reason>[a-z_]+) \((?P<detail>.+)\);"
    r" 'safeclean llm status' shows how to set them up\n"
)

Outcome = tuple[int, str, str]
T = TypeVar("T")


def safeclean(
    args: list[str],
    scan: ScanContext | None = None,
    *,
    env: Mapping[str, str] | None = None,
    auto: AutostartContext | None = None,
    limits: Limits = LIMITS,
) -> Outcome:
    """``safeclean <args>`` with the settings in ``env``: exit code, stdout, stderr."""
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        args,
        out=out,
        err=err,
        environment=Environment(
            scan_context=given(scan),
            autostart_context=given(auto),
            llm_env={} if env is None else env,
            llm_limits=limits,
        ),
    )
    return code, out.getvalue(), err.getvalue()


def given(context: T | None) -> Callable[[], T]:
    def factory() -> T:
        if context is None:
            raise AssertionError("this command was given no such context")
        return context

    return factory


def env_for(address: Address, **more: str) -> dict[str, str]:
    return {"SAFECLEAN_OLLAMA_URL": address.url, **more}


def free_address() -> Address:
    with socket.create_server(("127.0.0.1", 0)) as taken:
        return Address("127.0.0.1", taken.getsockname()[1])


def answer(text: str) -> Answer:
    return as_json({"response": text, "done": True})


def spy_on_connect(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    connected: list[object] = []
    connect = socket.socket.connect

    def spy(sock: socket.socket, address: Any) -> None:
        connected.append(address)
        connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", spy)
    return connected


def received(ollama: ScriptedOllama) -> str:
    """Every byte the server was sent that the scripted server keeps, as text."""
    parts = [f"{r.method} {r.path} {r.headers!r} " for r in ollama.received]
    return "".join(parts) + "".join(r.body.decode("utf-8") for r in ollama.received)


def aged(path: Path, data: bytes, days: int = 1) -> Path:
    write(path, data)
    stamp = time.time_ns() - days * DAY_NS
    os.utime(path, ns=(stamp, stamp))
    return path


# --- the three commands, each with what it explains ----------------------------------------------


def findings(zone: Path) -> list[str]:
    """``analyze``: four subjects in the order of its output. An old bytecode file, two more that
    share one subject, a duplicate copy (its older twin is kept), an old letter."""
    aged(zone / "old" / "__pycache__" / "c.cpython-313.pyc", b"cccc", days=40)
    aged(zone / "proj" / "__pycache__" / "b.cpython-313.pyc", b"bbb")
    aged(zone / "proj" / "__pycache__" / "a.cpython-313.pyc", b"aa")
    aged(zone / "photos" / "img.jpg", b"jpeg-bytes", days=10)
    aged(zone / "backup" / "img.jpg", b"jpeg-bytes", days=5)
    aged(zone / "archive" / "letter.txt", b"dear", days=40)
    return ["analyze", "--older-than", "30", str(zone)]


FINDINGS = [
    "level=safe, reasons=junk_cache:python-bytecode+old, extension=.pyc",
    "level=safe, reasons=junk_cache:python-bytecode, extension=.pyc",
    "level=likely_safe, reasons=duplicate_copy, extension=.jpg",
    "level=review, reasons=old, extension=.txt",
]
APP = b"[Desktop Entry]\nType=Application\nName=App\nExec=/usr/bin/app --tray\n"
TRAY = b"[Desktop Entry]\nType=Application\nName=Tray\nExec=tray\nHidden=true\n"
ENTRIES = [
    "source=xdg_autostart, scope=user, name=app, program=app, enabled=true",
    "source=xdg_autostart, scope=user, name=tray, program=tray, enabled=false",
]
STAYS = ["reason=junk, extension=.tmp", "reason=unknown_kind, extension=.qqq"]


@dataclass(frozen=True)
class Case:
    """One command that takes ``--explain``, on its tree, with the labels of its subjects."""

    args: list[str]
    scan: ScanContext
    auto: AutostartContext | None
    labels: list[str]

    def run(self, *more: str, env: Mapping[str, str] | None = None, **options: Any) -> Outcome:
        return safeclean([*self.args, *more], self.scan, env=env, auto=self.auto, **options)


def make_case(name: str, tmp_path: Path, zone: Path, scan: ScanContext) -> Case:
    if name == "analyze":
        return Case(findings(zone), scan, None, FINDINGS)
    if name == "autostart":
        write(tmp_path / "config" / "autostart" / "app.desktop", APP)
        write(tmp_path / "config" / "autostart" / "tray.desktop", TRAY)
        auto = autostart_context("linux", tmp_path)
        return Case(["autostart", "list"], scan, auto, ENTRIES)
    folder = zone / "Downloads"
    write(folder / "a.jpg", b"a")  # moves: not a subject
    write(folder / "notes.qqq", b"q")
    write(folder / "old.tmp", b"t")
    return Case(["organize", "move", str(folder)], scan, None, STAYS)


@pytest.fixture(params=["analyze", "autostart", "organize"])
def case(request: pytest.FixtureRequest, tmp_path: Path, zone: Path, scan: ScanContext) -> Case:
    return make_case(request.param, tmp_path, zone, scan)


def section(labels: list[str], texts: list[str], left_out: int = 0) -> str:
    lines = ["", HEADER]
    for label, text in zip(labels, texts, strict=True):
        lines += [f"  {label}", *(f"    {line}" for line in text.split("\n"))]
    if left_out:
        lines.append(f"  {left_out} more not explained (at most 20 per run)")
    return "\n".join(lines) + "\n"


def texts_for(case: Case) -> list[str]:
    return [f"Explanation {n}.\nSecond line {n}." for n in range(len(case.labels))]


# --- llm status ----------------------------------------------------------------------------------

SETTINGS = (
    "Settings: SAFECLEAN_OLLAMA_URL (a loopback address, default http://127.0.0.1:11434),\n"
    "  SAFECLEAN_OLLAMA_MODEL (default llama3.2)\n"
)
UNAVAILABLE_SETUP = (
    "AI explanations: unavailable; safeclean works as usual without them\n"
    "To set them up (safeclean installs nothing itself):\n"
)
INSTALL = "Install Ollama from https://ollama.com/download and start it"
AGAIN = "Check again: safeclean llm status"


def setup(*steps: str) -> str:
    numbered = "".join(f"  {n}. {step}\n" for n, step in enumerate(steps, start=1))
    return UNAVAILABLE_SETUP + numbered + SETTINGS


def test_status_when_everything_is_in_place() -> None:
    # [0013.15]
    with ScriptedOllama(VERSION, TAGS) as ollama:
        code, out, err = safeclean(["llm", "status"], env=env_for(ollama.address))
    assert (code, err) == (0, "")
    assert out == (
        f"Ollama: running at {ollama.address.url} (version 0.6.2)\n"
        "Model: llama3.2: installed\n"
        "AI explanations: available with --explain on analyze, autostart list and organize move\n"
    )
    assert ollama.paths() == CHECKS


def test_status_names_the_model_of_the_setting() -> None:
    # [0013.15]
    with ScriptedOllama(VERSION, TAGS) as ollama:
        env = env_for(ollama.address, SAFECLEAN_OLLAMA_MODEL="qwen2.5:7b")
        code, out, _ = safeclean(["llm", "status"], env=env)
    assert code == 0
    assert out.splitlines()[1] == "Model: qwen2.5:7b: installed"


def test_status_when_ollama_is_not_reached() -> None:
    # [0013.15] Every step, numbered from 1.
    address = free_address()
    code, out, err = safeclean(["llm", "status"], env=env_for(address))
    first, rest = out.split("\n", 1)
    assert (code, err) == (1, "")
    assert re.fullmatch(rf"Ollama: not reachable at {re.escape(address.url)} \(.+\)", first)
    assert rest == (
        "Model: llama3.2: not checked\n"
        "AI explanations: unavailable; safeclean works as usual without them\n"
        "To set them up (safeclean installs nothing itself):\n"
        "  1. Install Ollama from https://ollama.com/download and start it\n"
        "  2. Download the model: ollama pull llama3.2\n"
        "  3. Check again: safeclean llm status\n"
        "Settings: SAFECLEAN_OLLAMA_URL (a loopback address, default http://127.0.0.1:11434),\n"
        "  SAFECLEAN_OLLAMA_MODEL (default llama3.2)\n"
    )


def test_status_when_ollama_does_not_answer_in_time() -> None:
    # [0013.15]
    with ScriptedOllama(LATE_VERSION) as ollama:
        code, out, _ = safeclean(["llm", "status"], env=env_for(ollama.address), limits=QUICK)
    assert code == 1
    assert out == (
        f"Ollama: not reachable at {ollama.address.url} (no whole answer before the deadline)\n"
        "Model: llama3.2: not checked\n"
    ) + setup(INSTALL, "Download the model: ollama pull llama3.2", AGAIN)


@pytest.mark.parametrize(
    ("script", "detail"),
    [
        ([as_json({}, 404)], "GET /api/version: status 404"),
        ([redirect("http://example.com/")], "302 to 'http://example.com/', not followed"),
        ([VERSION, as_json({"models": 3})], "GET /api/tags: no list of models"),
    ],
)
def test_status_of_something_else(script: list[Answer], detail: str) -> None:
    # [0013.15]
    with ScriptedOllama(*script) as ollama:
        code, out, _ = safeclean(["llm", "status"], env=env_for(ollama.address))
    assert code == 1
    assert out == (
        f"Ollama: {ollama.address.url} does not answer as Ollama ({detail})\n"
        "Model: llama3.2: not checked\n"
    ) + setup(INSTALL, "Download the model: ollama pull llama3.2", AGAIN)


def test_status_when_the_model_is_missing() -> None:
    # [0013.15] Ollama runs: no step to install it, the others numbered from 1.
    with ScriptedOllama(VERSION, NO_MODELS) as ollama:
        code, out, _ = safeclean(["llm", "status"], env=env_for(ollama.address))
    assert code == 1
    assert out == (
        f"Ollama: running at {ollama.address.url} (version 0.6.2)\n"
        "Model: llama3.2: not installed\n"
        "AI explanations: unavailable; safeclean works as usual without them\n"
        "To set them up (safeclean installs nothing itself):\n"
        "  1. Download the model: ollama pull llama3.2\n"
        "  2. Check again: safeclean llm status\n"
        "Settings: SAFECLEAN_OLLAMA_URL (a loopback address, default http://127.0.0.1:11434),\n"
        "  SAFECLEAN_OLLAMA_MODEL (default llama3.2)\n"
    )


URL_REFUSED = (
    "refused setting SAFECLEAN_OLLAMA_URL='https://example.com'"
    " (not http://HOST[:PORT] with a loopback HOST)"
)
MODEL_REFUSED = "refused setting SAFECLEAN_OLLAMA_MODEL='?' (not a model name)"


@pytest.mark.parametrize(
    ("env", "lines", "steps"),
    [
        (
            {"SAFECLEAN_OLLAMA_URL": "https://example.com", "SAFECLEAN_OLLAMA_MODEL": "qwen2.5:7b"},
            [f"Ollama: {URL_REFUSED}", "Model: qwen2.5:7b: not checked"],
            ["Download the model: ollama pull qwen2.5:7b", AGAIN],
        ),
        (
            {"SAFECLEAN_OLLAMA_URL": "http://127.0.0.1:9", "SAFECLEAN_OLLAMA_MODEL": "?"},
            ["Ollama: not checked", f"Model: {MODEL_REFUSED}"],
            [AGAIN],
        ),
        (
            {"SAFECLEAN_OLLAMA_URL": "https://example.com", "SAFECLEAN_OLLAMA_MODEL": "?"},
            [f"Ollama: {URL_REFUSED}", f"Model: {MODEL_REFUSED}"],
            [AGAIN],
        ),
    ],
    ids=["address", "model", "both"],
)
def test_status_with_a_refused_setting(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], lines: list[str], steps: list[str]
) -> None:
    # [0013.15] Nothing is contacted.
    connected = spy_on_connect(monkeypatch)
    code, out, _ = safeclean(["llm", "status"], env=env)
    assert (code, connected) == (1, [])
    assert out == "".join(f"{line}\n" for line in lines) + setup(*steps)


# --- off unless asked, and never with what acts ----------------------------------------------


def test_without_explain_nothing_is_contacted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, zone: Path, scan: ScanContext
) -> None:
    # [0013.1] With Ollama running and the settings pointing at it.
    connected = spy_on_connect(monkeypatch)
    folder = make_case("organize", tmp_path, zone, scan).args[-1]
    auto = make_case("autostart", tmp_path, zone, scan).auto
    analyze = findings(zone)
    with ScriptedOllama(VERSION, TAGS, answer("Never asked.")) as ollama:
        env = env_for(ollama.address)
        for args in (
            analyze,
            [*analyze, "--json"],
            ["scan", str(zone)],
            ["organize", "move", folder],
            ["organize", "move", folder, "--yes"],
            ["organize", "list"],
            ["quarantine", "list"],
        ):
            assert safeclean(args, scan, env=env)[0] in (0, 1)
        for args in (["autostart", "list"], ["autostart", "list", "--json"], ["recover"]):
            assert safeclean(args, scan, env=env, auto=auto)[0] == 0
    assert (ollama.connections, connected) == (0, [])


@pytest.mark.parametrize("order", [["--yes", "--explain"], ["--explain", "--yes"]])
def test_explain_with_yes_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    zone: Path,
    scan: ScanContext,
    data_dir: Path,
    order: list[str],
) -> None:
    # [0013.3] [0013.25] Before anything else: nothing moved, no journal, nothing contacted.
    organize = make_case("organize", tmp_path, zone, scan)
    before = snapshot(zone)
    with (
        ScriptedOllama(VERSION, TAGS, answer("Never asked.")) as ollama,
        pytest.raises(SystemExit) as raised,
    ):
        organize.run(*order, env=env_for(ollama.address))
    assert raised.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err
    assert snapshot(zone) == before
    assert not data_dir.exists()
    assert ollama.connections == 0


@pytest.mark.parametrize(
    "args",
    [
        ["scan"],
        ["quarantine", "add", "x"],
        ["quarantine", "add", "--from-analysis", "--level", "safe"],
        ["quarantine", "list"],
        ["quarantine", "restore", "1"],
        ["quarantine", "purge", "1"],
        ["organize", "undo", "1"],
        ["organize", "list"],
        ["autostart", "disable", "abc"],
        ["autostart", "enable", "abc"],
        ["autostart", "recover"],
        ["recover"],
        ["llm", "status"],
    ],
    ids=lambda args: " ".join(args),
)
def test_other_commands_have_no_explain(
    capsys: pytest.CaptureFixture[str], scan: ScanContext, args: list[str]
) -> None:
    # [0013.3] [0013.25]
    with pytest.raises(SystemExit) as raised:
        safeclean([*args, "--explain"], scan)
    assert raised.value.code == 2
    assert "unrecognized arguments: --explain" in capsys.readouterr().err


def test_a_refused_move_with_explain_contacts_nothing(
    tmp_path: Path, zone: Path, data_dir: Path
) -> None:
    # [0013.25] Refused as without it (0012 item 37), before the journal and before Ollama.
    mac = scan_context(tmp_path, zone, data_dir, platform="darwin")
    organize = make_case("organize", tmp_path, zone, mac)
    without = organize.run()
    with ScriptedOllama(VERSION, TAGS, answer("Never asked.")) as ollama:
        assert organize.run("--explain", env=env_for(ollama.address)) == without
    assert without[0] == 3
    assert ollama.connections == 0
    assert not data_dir.exists()


# --- what is sent --------------------------------------------------------------------------------


def test_explain_sends_nothing_of_the_files(tmp_path: Path, zone: Path, scan: ScanContext) -> None:
    # [0013.5] Names, folders, contents, arguments and notes are markers: none reaches Ollama.
    aged(zone / "markerdir1" / "__pycache__" / "marker1.cpython-313.pyc", b"marker-content-1")
    aged(zone / "markerdir2" / "marker2.jpg", b"marker-content-2", days=10)
    aged(zone / "markerdir3" / "marker2.jpg", b"marker-content-2", days=5)
    aged(zone / "markerdir4" / "marker3.txt", b"marker-content-3", days=40)
    entry = b"[Desktop Entry]\nType=Application\nName=App\nComment=marker-comment\n"
    entry += b"Exec=/opt/markerdir5/app --marker-argument\nOnlyShowIn=markerdesktop;\n"
    write(tmp_path / "config" / "autostart" / "app.desktop", entry)  # its name is sent
    folder = zone / "markerfolder"
    write(folder / "marker5.qqq", b"marker-content-5")
    write(folder / "marker6.tmp", b"marker-content-6")
    (folder / "markersub").mkdir()
    auto = autostart_context("linux", tmp_path)
    runs = [
        (["analyze", "--older-than", "30", str(zone)], None, 4),  # marker6.tmp too
        (["autostart", "list"], auto, 1),
        (["organize", "move", str(folder)], None, 3),
    ]
    for args, listing, subjects in runs:
        with ScriptedOllama(VERSION, TAGS, answer("Explained.")) as ollama:
            explained = safeclean(
                [*args, "--explain"], scan, env=env_for(ollama.address), auto=listing
            )
        assert HEADER in explained[1]
        assert ollama.paths() == [*CHECKS, *[GENERATE] * subjects]
        assert "marker" not in received(ollama).lower()


# --- without Ollama, everything works ------------------------------------------------------------

REASONS = ["unreachable", "model_missing", "timeout", "config"]


@pytest.mark.parametrize("reason", REASONS)
def test_without_ollama_nothing_changes(case: Case, reason: str) -> None:
    # [0013.4] [0013.24] Same stdout, same exit code, and one line on stderr naming the cause.
    without = case.run()
    details = {
        "model_missing": "'llama3.2' is not among the 0 models listed",
        "timeout": "no whole answer before the deadline",
        "config": "SAFECLEAN_OLLAMA_URL='http://192.0.2.1:11434': not a loopback address",
    }
    script = [VERSION, NO_MODELS] if reason == "model_missing" else [LATE_VERSION]
    with ScriptedOllama(*script) as ollama:
        env = {
            "unreachable": env_for(free_address()),
            "model_missing": env_for(ollama.address),
            "timeout": env_for(ollama.address),
            "config": {"SAFECLEAN_OLLAMA_URL": "http://192.0.2.1:11434"},
        }[reason]
        code, out, err = case.run("--explain", env=env, limits=QUICK)
    assert (code, out) == without[:2]
    assert err.startswith(without[2])
    line = UNAVAILABLE.fullmatch(err[len(without[2]) :])
    assert line is not None
    assert line["reason"] == reason
    assert line["detail"] == details.get(reason, line["detail"])


def test_stdout_without_explain_is_the_beginning(case: Case) -> None:
    # [0013.24] [0013.26] Byte for byte, then one empty line and the section; nothing on stderr.
    code, out, err = case.run()
    texts = texts_for(case)
    with ScriptedOllama(VERSION, TAGS, *map(answer, texts)) as ollama:
        explained = case.run("--explain", env=env_for(ollama.address))
    assert explained == (code, out + section(case.labels, texts), err)
    assert ollama.paths() == [*CHECKS, *[GENERATE] * len(texts)]


def test_a_stopped_run_says_after_how_many(tmp_path: Path, zone: Path, scan: ScanContext) -> None:
    # [0013.24] The explanation received is shown; nothing is asked after the failure.
    analyze = make_case("analyze", tmp_path, zone, scan)
    code, out, err = analyze.run()
    with ScriptedOllama(VERSION, TAGS, answer("First."), as_json({}, 500)) as ollama:
        explained = analyze.run("--explain", env=env_for(ollama.address))
    stopped = "AI explanations stopped after 1: http_status (POST /api/generate: status 500)\n"
    assert explained == (code, out + section(FINDINGS[:1], ["First."]), err + stopped)
    assert ollama.paths() == [*CHECKS, GENERATE, GENERATE]


def test_the_section(tmp_path: Path, zone: Path, scan: ScanContext) -> None:
    # [0013.26] The model of the setting; each label, then its answer indented, in the order
    # of the command's output.
    organize = make_case("organize", tmp_path, zone, scan)
    first = "A temporary file.\nPrograms leave these behind."
    with ScriptedOllama(VERSION, TAGS, answer(first), answer("An unknown kind.")) as ollama:
        env = env_for(ollama.address, SAFECLEAN_OLLAMA_MODEL="qwen2.5:7b")
        _, out, _ = organize.run("--explain", env=env)
    assert out.endswith(
        "Nothing was moved. Re-run with --yes to move these files.\n"
        "\n"
        "AI explanations (qwen2.5:7b via Ollama; advisory, may be wrong; nothing above depends on"
        " them):\n"
        "  reason=junk, extension=.tmp\n"
        "    A temporary file.\n"
        "    Programs leave these behind.\n"
        "  reason=unknown_kind, extension=.qqq\n"
        "    An unknown kind.\n"
    )


def test_the_section_counts_what_the_budget_left_out(zone: Path, scan: ScanContext) -> None:
    # [0013.26] 22 subjects: 20 asked, the last line counts the 2 others.
    folder = zone / "Downloads"
    for n in range(22):
        write(folder / f"f{n:02}.q{n:02}", b"?")
    with ScriptedOllama(VERSION, TAGS, answer("Unknown.")) as ollama:
        args = ["organize", "move", str(folder), "--explain"]
        code, out, _ = safeclean(args, scan, env=env_for(ollama.address))
    assert code == 1
    assert out.endswith(
        "  reason=unknown_kind, extension=.q19\n"
        "    Unknown.\n"
        "  2 more not explained (at most 20 per run)\n"
    )
    assert ollama.paths().count(GENERATE) == 20


def test_nothing_to_explain_means_no_section(tmp_path: Path, zone: Path, scan: ScanContext) -> None:
    # [0013.26] An empty zone, a refused folder: no section, no line, no connection.
    with ScriptedOllama(VERSION, TAGS) as ollama:
        env = env_for(ollama.address)
        empty = safeclean(["analyze", str(zone)], scan, env=env)
        assert safeclean(["analyze", "--explain", str(zone)], scan, env=env) == empty
        refused = safeclean(["organize", "move", str(tmp_path / "nowhere")], scan, env=env)
        args = ["organize", "move", str(tmp_path / "nowhere"), "--explain"]
        assert safeclean(args, scan, env=env) == refused
    assert ollama.connections == 0


# --- JSON ----------------------------------------------------------------------------------------

FOUR = [
    "explanations",
    "explanations_model",
    "explanations_not_explained",
    "explanations_unavailable",
]


def json_case(name: str, tmp_path: Path, zone: Path, scan: ScanContext) -> Case:
    made = make_case(name, tmp_path, zone, scan)
    return Case([*made.args, "--json"], made.scan, made.auto, made.labels)


def test_each_output_has_its_own_order(tmp_path: Path, scan: ScanContext) -> None:
    # [0013.18] The text groups autostart entries by source; JSON keeps the order they were read.
    registry = FakeRegistry(
        {
            (Hive.HKCU, RUN): [RegValue("Sync", ValueKind.REG_SZ, "sync.exe")],
            (Hive.HKCU, RUN_ONCE): [RegValue("Once", ValueKind.REG_SZ, "once.exe")],
            (Hive.HKLM, RUN): [RegValue("Agent", ValueKind.REG_SZ, "agent.exe")],
        }
    )
    auto = autostart_context("windows", tmp_path, registry)
    asked: dict[str, list[str]] = {}
    for more in ([], ["--json"]):
        with ScriptedOllama(VERSION, TAGS, answer("Explained.")) as ollama:
            args = ["autostart", "list", "--include-machine", "--explain", *more]
            safeclean(args, scan, env=env_for(ollama.address), auto=auto)
        prompts = [json.loads(json.loads(r.body)["prompt"]) for r in ollama.received[2:]]
        asked["json" if more else "text"] = [prompt["name"] for prompt in prompts]
    assert asked == {"text": ["Sync", "Agent", "Once"], "json": ["Sync", "Once", "Agent"]}


@pytest.mark.parametrize("name", ["analyze", "autostart"])
def test_json_keeps_every_key_and_adds_four(
    tmp_path: Path, zone: Path, scan: ScanContext, name: str
) -> None:
    # [0013.27]
    json_run = json_case(name, tmp_path, zone, scan)
    _, out, _ = json_run.run()
    texts = texts_for(json_run)
    with ScriptedOllama(VERSION, TAGS, *map(answer, texts)) as ollama:
        code, explained, err = json_run.run("--explain", env=env_for(ollama.address))
    plain, data = json.loads(out), json.loads(explained)
    assert (code, err) == (0, "")
    assert list(data) == [*plain, *FOUR]
    assert {key: data[key] for key in plain} == plain
    assert [one["text"] for one in data["explanations"]] == texts
    assert data["explanations_model"] == "llama3.2"
    assert data["explanations_not_explained"] == 0
    assert data["explanations_unavailable"] is None


def test_json_subjects_are_their_facts(tmp_path: Path, zone: Path, scan: ScanContext) -> None:
    # [0013.27] The kind, then the facts as JSON: a list is a list, a flag is a flag.
    analyze = json_case("analyze", tmp_path, zone, scan)
    auto = json_case("autostart", tmp_path, zone, scan)
    with ScriptedOllama(VERSION, TAGS, answer("Explained.")) as ollama:
        found = json.loads(analyze.run("--explain", env=env_for(ollama.address))[1])
    with ScriptedOllama(VERSION, TAGS, answer("Explained.")) as ollama:
        listed = json.loads(auto.run("--explain", env=env_for(ollama.address))[1])
    assert found["explanations"][0] == {
        "subject": {
            "kind": "finding",
            "level": "safe",
            "reasons": ["junk_cache:python-bytecode", "old"],
            "extension": ".pyc",
        },
        "text": "Explained.",
    }
    assert [one["subject"] for one in listed["explanations"]] == [
        {
            "kind": "autostart",
            "source": "xdg_autostart",
            "scope": "user",
            "name": name,
            "program": program,
            "enabled": enabled,
        }
        for name, program, enabled in (("app", "app", True), ("tray", "tray", False))
    ]


def test_json_without_an_explanation(tmp_path: Path, zone: Path, scan: ScanContext) -> None:
    # [0013.27] The four keys say why; the line on stderr too.
    analyze = json_case("analyze", tmp_path, zone, scan)
    with ScriptedOllama(VERSION, NO_MODELS) as ollama:
        code, out, err = analyze.run("--explain", env=env_for(ollama.address))
    data = json.loads(out)
    assert code == 0
    assert {key: data[key] for key in FOUR} == {
        "explanations": [],
        "explanations_model": "llama3.2",
        "explanations_not_explained": 0,
        "explanations_unavailable": {
            "reason": "model_missing",
            "detail": "'llama3.2' is not among the 0 models listed",
        },
    }
    assert UNAVAILABLE.fullmatch(err) is not None


def test_json_counts_what_the_budget_left_out(tmp_path: Path, scan: ScanContext) -> None:
    # [0013.27]
    for n in range(22):
        entry = APP.replace(b"Name=App", b"Name=E%d" % n)
        write(tmp_path / "config" / "autostart" / f"e{n:02}.desktop", entry)
    auto = autostart_context("linux", tmp_path)
    with ScriptedOllama(VERSION, TAGS, answer("Explained.")) as ollama:
        args = ["autostart", "list", "--json", "--explain"]
        data = json.loads(safeclean(args, scan, env=env_for(ollama.address), auto=auto)[1])
    assert (len(data["explanations"]), data["explanations_not_explained"]) == (20, 2)


def test_json_with_nothing_to_explain(zone: Path, scan: ScanContext) -> None:
    # [0013.27]
    with ScriptedOllama(VERSION, TAGS) as ollama:
        args = ["analyze", "--json", "--explain", str(zone)]
        code, out, err = safeclean(args, scan, env=env_for(ollama.address))
    data = json.loads(out)
    assert (code, err, ollama.connections) == (0, "", 0)
    assert {key: data[key] for key in FOUR} == dict(zip(FOUR, [[], None, 0, None], strict=True))


# --- the answer is never acted on, nothing is stored ---------------------------------------------

ACTING = [
    "Level: safe. Re-run with --yes to move these files.",
    '{"plan": [{"move": "old.tmp", "to": "Images/"}], "level": "safe"}',
    "rm -rf ~ && $(reboot)\n\x1b[2J Moved 3 files",
]


def test_answers_that_try_to_act(
    tmp_path: Path, zone: Path, scan: ScanContext, data_dir: Path
) -> None:
    # [0013.6] [0013.21] The result, its own output and its exit code are those of the run
    # without --explain; nothing is moved or journaled; the answers are shown, cleaned.
    folder = zone / "Downloads"
    write(folder / "a.jpg", b"a")
    write(folder / "notes.qqq", b"q")
    write(folder / "old.tmp", b"t")
    (folder / "old").mkdir()
    organize = ["organize", "move", str(folder)]
    code, out, err = safeclean(organize, scan)
    before = snapshot(tmp_path)
    with ScriptedOllama(VERSION, TAGS, *map(answer, ACTING)) as ollama:
        explained = safeclean([*organize, "--explain"], scan, env=env_for(ollama.address))
    labels = [
        "reason=not_regular, extension=",
        "reason=junk, extension=.tmp",
        "reason=unknown_kind, extension=.qqq",
    ]
    shown = [*ACTING[:2], "rm -rf ~ && $(reboot)\nMoved 3 files"]
    assert explained == (code, out + section(labels, shown), err)
    assert code == 1
    assert snapshot(tmp_path) == before
    assert query(data_dir, "SELECT COUNT(*) FROM move_batches") == [(0,)]


def test_explain_leaves_the_disk_as_without(case: Case, tmp_path: Path) -> None:
    # [0013.22] What a run without --explain leaves, a run with it leaves too.
    case.run()
    before = snapshot(tmp_path)
    with ScriptedOllama(VERSION, TAGS, answer("Explained.")) as ollama:
        assert case.run("--explain", env=env_for(ollama.address))[1].endswith("Explained.\n")
    assert snapshot(tmp_path) == before
