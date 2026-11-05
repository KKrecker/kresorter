"""``kresorter llm status`` and ``--explain`` (decision 0013, items 1, 3-6, 15 and 24-27).

Off unless asked: only ``llm status`` and a run with ``--explain`` contact Ollama, or LM Studio
when ``KRESORTER_LLM_SERVER`` names it (decision 0019, items 10 and 11), and
``--explain`` is on the report commands and on ``organize move`` without ``--yes``. A command's
own result is final before anything is asked, and its output is written first: the
explanations follow it under a fixed label (text) or as four added keys (JSON). A run that gets
none, or stops, says so in one line on stderr, with the same stdout and exit code.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TextIO

from kresorter.llm.client import Status, status
from kresorter.llm.explain import BUDGET, Explanations, explain
from kresorter.llm.failure import ExplanationUnavailable, SettingRefused, Unavailable
from kresorter.llm.settings import (
    SERVER_NAMES,
    SERVER_VARIABLE,
    Server,
    model_from,
    variables,
)
from kresorter.llm.subjects import Fact, Result, Subject, subjects
from kresorter.llm.transport import LIMITS, Limits

HEADER = "AI explanations ({} via {}; advisory, may be wrong; nothing above depends on them):"
UNAVAILABLE = (
    "AI explanations unavailable: {} ({}); 'kresorter llm status' shows how to set them up\n"
)
STOPPED = "AI explanations stopped after {}: {} ({})\n"
AVAILABLE = "AI explanations: available with --explain on analyze, autostart list and organize move"
SETUP = [
    "AI explanations: unavailable; kresorter works as usual without them",
    "To set them up (kresorter installs nothing itself):",
]


def settings_lines(server: Server) -> list[str]:
    """The settings of ``server``, after the one that chooses it (decision 0019, item 10)."""
    named = variables(server)
    model = named.default_model or "the first model LM Studio lists"
    return [
        f"Settings: {SERVER_VARIABLE} (ollama or lmstudio, default ollama),",
        f"  {named.url} (a loopback address, default {named.address.url}),",
        f"  {named.model} (default {model})",
    ]


SETTINGS = settings_lines("ollama")
LMSTUDIO_SETTINGS = settings_lines("lmstudio")
INSTALL = "Install Ollama from https://ollama.com/download and start it"
PULL = "Download the model: ollama pull {}"
LMSTUDIO_INSTALL = (
    "Install LM Studio from https://lmstudio.ai, download a model and start its server"
    " (Developer, Start Server)"
)
LMSTUDIO_DOWNLOAD = "Download the model in LM Studio: {}"
AGAIN = "Check again: kresorter llm status"
_INSTALL: dict[Server, str] = {"ollama": INSTALL, "lmstudio": LMSTUDIO_INSTALL}
_DOWNLOAD: dict[Server, str] = {"ollama": PULL, "lmstudio": LMSTUDIO_DOWNLOAD}
_FOUND: dict[Server, str] = {"ollama": "installed", "lmstudio": "available"}
_NOT_REACHED = frozenset({Unavailable.UNREACHABLE, Unavailable.TIMEOUT})
_LOCAL = "Local AI"  # the first line's name when the server itself is refused


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    llm = commands.add_parser(
        "llm", help="optional AI explanations from a local Ollama or LM Studio"
    )
    actions = llm.add_subparsers(dest="action", required=True)
    actions.add_parser("status", help="check whether AI explanations can be given")


def add_explain(parser: argparse.ArgumentParser | argparse._MutuallyExclusiveGroup) -> None:
    parser.add_argument(
        "--explain",
        action="store_true",
        help=(
            "add advisory explanations from a local Ollama or LM Studio"
            " ('kresorter llm status' checks it)"
        ),
    )


@dataclass(frozen=True)
class Explainer:
    """Where a run's explanations come from: the environment of the settings, the deadlines."""

    env: Mapping[str, str]
    limits: Limits = LIMITS

    def __call__(self, results: Iterable[Result]) -> Explanations:
        return explain(subjects(results), self.env, limits=self.limits)


def ask(explainer: Explainer | None, results: Iterable[Result]) -> Explanations | None:
    """The explanations of ``results``, in the order the command showed them; ``None`` without
    ``--explain``."""
    return None if explainer is None else explainer(results)


# --- --explain ---------------------------------------------------------------------------------


def section(explained: Explanations | None) -> str:
    """What follows the command's own text output: nothing when no explanation came."""
    if explained is None or not explained.explained:
        return ""
    lines = ["", HEADER.format(explained.model, SERVER_NAMES[explained.server])]
    for one in explained.explained:
        lines.append(f"  {label(one.subject)}")
        lines += [f"    {line}" for line in one.text.split("\n")]
    if explained.not_explained:
        left_out = explained.not_explained
        lines.append(f"  {left_out} more not explained (at most {BUDGET} per run)")
    return "\n".join(lines) + "\n"


def label(subject: Subject) -> str:
    """The facts as ``name=value``, joined by ``, ``; a list's values joined by ``+``."""
    return ", ".join(f"{name}={_value(fact)}" for name, fact in subject.pairs if name != "kind")


def _value(fact: Fact) -> str:
    if isinstance(fact, bool):
        return "true" if fact else "false"
    if isinstance(fact, tuple):
        return "+".join(fact)
    return fact


def notify(explained: Explanations | None, err: TextIO) -> None:
    """One line on stderr when explanations are missing or stopped, none otherwise."""
    if explained is None or explained.unavailable is None:
        return
    failed = explained.unavailable
    if explained.explained:
        err.write(STOPPED.format(len(explained.explained), failed.reason, failed.detail))
    else:
        err.write(UNAVAILABLE.format(failed.reason, failed.detail))


def json_keys(explained: Explanations | None) -> dict[str, Any]:
    """The four keys ``--explain`` adds to a JSON report; none without it."""
    if explained is None:
        return {}
    failed = explained.unavailable
    return {
        "explanations": [{"subject": e.subject.facts, "text": e.text} for e in explained.explained],
        "explanations_model": explained.model,
        "explanations_not_explained": explained.not_explained,
        "explanations_unavailable": (
            None if failed is None else {"reason": str(failed.reason), "detail": failed.detail}
        ),
    }


# --- llm status --------------------------------------------------------------------------------


def run_status(env: Mapping[str, str], out: TextIO, limits: Limits = LIMITS) -> int:
    """What is in place and, when something is not, how to set it up: exit 0 or 1."""
    found = status(env, limits=limits)
    server = found.server
    running, install = _server(found)
    model, download = _model(found, env)
    named = _LOCAL if _refused_server(found) else SERVER_NAMES[server]
    lines = [f"{named}: {running}", f"Model: {model}"]
    if found.failure is None:
        out.write("\n".join([*lines, AVAILABLE]) + "\n")
        return 0
    none_listed = found.installed is False and found.model is None  # LM Studio has none
    steps = [_INSTALL[server]] if install or none_listed else []
    steps += [] if download is None else [_DOWNLOAD[server].format(download)]
    numbered = [f"  {n}. {step}" for n, step in enumerate([*steps, AGAIN], start=1)]
    out.write("\n".join([*lines, *SETUP, *numbered, *settings_lines(server)]) + "\n")
    return 1


def _refused_server(found: Status) -> bool:
    return isinstance(found.failure, SettingRefused) and found.failure.name == SERVER_VARIABLE


def _server(found: Status) -> tuple[str, bool]:
    """The server's line, and whether installing and starting the server is a step."""
    url = None if found.address is None else found.address.url
    refused_here = (SERVER_VARIABLE, variables(found.server).url)
    match found.failure:
        case SettingRefused() as refused if refused.name in refused_here:
            return _refused(refused), False
        case SettingRefused():
            return "not checked", False
        case ExplanationUnavailable() as failed if found.installed is None:
            if failed.reason in _NOT_REACHED:
                return f"not reachable at {url} ({failed.detail})", True
            named = SERVER_NAMES[found.server]
            return f"{url} does not answer as {named} ({failed.detail})", True
        case _ if found.version is None:
            return f"running at {url}", False  # LM Studio says no version
        case _:
            return f"running at {url} (version {found.version})", False


def _model(found: Status, env: Mapping[str, str]) -> tuple[str, str | None]:
    """The model line, and the model to download when that is a step."""
    word = _FOUND[found.server]
    if found.installed is not None:
        if found.installed:
            return f"{found.model}: {word}", None
        if found.model is None:
            return "none listed", None
        return f"{found.model}: not {word}", found.model
    try:
        model = model_from(env)  # read here too: the checks stop at a refused address
    except SettingRefused as refused:
        return ("not checked" if refused.name == SERVER_VARIABLE else _refused(refused)), None
    if model is None:
        return "not checked", None
    return f"{model}: not checked", model


def _refused(refused: SettingRefused) -> str:
    return f"refused setting {refused.name}={refused.value!r} ({refused.why})"
