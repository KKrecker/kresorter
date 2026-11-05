"""One run's explanations: the checks once, a budget, the first failure ends it (decision 0013).

Item 13. ``explain`` takes the run's subjects in order, checks Ollama once (item 14), then
asks for each subject until the budget is spent or a request fails; a run with nothing to
explain opens no connection. Scripts are in the order of the requests: ``version``, ``tags``,
then one ``generate`` per subject.
"""

import inspect
import json
import socket
from typing import Any

import pytest

from kresorter.llm.explain import BUDGET, Explained, Explanations, explain
from kresorter.llm.failure import Unavailable
from kresorter.llm.prompt import Language
from kresorter.llm.settings import Address
from kresorter.llm.subjects import Subject
from kresorter.llm.transport import Limits
from support.ollama import Answer, ScriptedOllama, after, as_json, head

VERSION = as_json({"version": "0.6.2"})
TAGS = as_json({"models": [{"name": "llama3.2:latest"}, {"name": "qwen2.5:7b"}]})
CHECKS = [("GET", "/api/version"), ("GET", "/api/tags")]
GENERATE = ("POST", "/api/generate")
QUICK = Limits(check_seconds=3.0, generate_seconds=0.3)


def subject(n: int) -> Subject:
    return Subject((("kind", "stay"), ("reason", "unknown_kind"), ("extension", f".x{n}")))


def answer(text: str) -> Answer:
    return as_json({"response": text, "done": True})


def env_for(address: Address, **more: str) -> dict[str, str]:
    return {"KRESORTER_OLLAMA_URL": address.url, **more}


def texts(run: Explanations) -> list[str]:
    return [explained.text for explained in run.explained]


def test_each_subject_is_asked_in_order_after_the_checks_run_once() -> None:
    # [0013.13] version and tags once, before the first generate; each subject's own answer.
    asked = [subject(n) for n in range(3)]
    script = [answer(f"Answer {n}.") for n in range(3)]
    with ScriptedOllama(VERSION, TAGS, *script) as ollama:
        run = explain(asked, env_for(ollama.address))
    assert ollama.paths() == [*CHECKS, GENERATE, GENERATE, GENERATE]
    assert run == Explanations(
        model="llama3.2",
        explained=tuple(Explained(s, f"Answer {n}.") for n, s in enumerate(asked)),
        not_explained=0,
        unavailable=None,
    )
    prompts = [json.loads(json.loads(received.body)["prompt"]) for received in ollama.received[2:]]
    assert [prompt["extension"] for prompt in prompts] == [".x0", ".x1", ".x2"]


def test_the_model_asked_is_the_setting() -> None:
    # [0013.13]
    with ScriptedOllama(VERSION, TAGS, answer("Qwen's answer.")) as ollama:
        run = explain([subject(0)], env_for(ollama.address, KRESORTER_OLLAMA_MODEL="qwen2.5:7b"))
    assert (run.model, texts(run)) == ("qwen2.5:7b", ["Qwen's answer."])
    assert b'"model": "qwen2.5:7b"' in ollama.received[2].body


@pytest.mark.parametrize(("language", "named"), [("en", "English"), ("ru", "Russian")])
def test_each_subject_is_asked_in_the_language_given(language: Language, named: str) -> None:
    # [0019.1] English when none is given, as the console asks.
    with ScriptedOllama(VERSION, TAGS, answer("One."), VERSION, TAGS, answer("Two.")) as ollama:
        explain([subject(0)], env_for(ollama.address), language=language)
        explain([subject(1)], env_for(ollama.address))
    systems = [json.loads(received.body)["system"] for received in ollama.received[2::3]]
    assert [system.rsplit(". ", 1)[-1] for system in systems] == [
        f"Write the answer in {named}.",
        "Write the answer in English.",
    ]


def test_at_most_20_requests_per_run() -> None:
    # [0013.13] 25 subjects: 20 asked, 5 counted as not explained.
    with ScriptedOllama(VERSION, TAGS, answer("An answer.")) as ollama:
        run = explain([subject(n) for n in range(25)], env_for(ollama.address))
    assert ollama.paths() == [*CHECKS] + [GENERATE] * 20
    assert [e.subject for e in run.explained] == [subject(n) for n in range(20)]
    assert (run.not_explained, run.unavailable) == (5, None)


@pytest.mark.parametrize(("count", "left_out"), [(19, 0), (20, 0), (21, 1)])
def test_the_budget_is_20(count: int, left_out: int) -> None:
    # [0013.13]
    assert BUDGET == 20
    assert inspect.signature(explain).parameters["budget"].default == BUDGET
    with ScriptedOllama(VERSION, TAGS, answer("An answer.")) as ollama:
        run = explain([subject(n) for n in range(count)], env_for(ollama.address))
    assert (len(run.explained), run.not_explained) == (count - left_out, left_out)


def late(seconds: float, data: bytes = b'{"response": "Too late.", "done": true}') -> Answer:
    return after(seconds, head(200, length=len(data)) + data)


@pytest.mark.parametrize(
    ("third", "reason"),
    [
        (late(0.6), Unavailable.TIMEOUT),
        (as_json({"error": "out of memory"}, 500), Unavailable.HTTP_STATUS),
        (as_json({"response": "half", "done": False}), Unavailable.BAD_RESPONSE),
        (answer("\x1b[2J\u200b"), Unavailable.EMPTY),
        (answer("x" * 70_000), Unavailable.TOO_LARGE),
    ],
)
def test_the_first_failure_stops_the_run(third: Answer, reason: Unavailable) -> None:
    # [0013.13] Whatever the reason: no fourth request, the two answers kept, the reason too.
    first, second, fourth = answer("First."), answer("Second."), answer("Fourth.")
    with ScriptedOllama(VERSION, TAGS, first, second, third, fourth) as ollama:
        run = explain([subject(n) for n in range(5)], env_for(ollama.address), limits=QUICK)
    assert ollama.paths() == [*CHECKS, GENERATE, GENERATE, GENERATE]
    assert texts(run) == ["First.", "Second."]
    assert run.unavailable is not None
    assert run.unavailable.reason is reason
    assert run.not_explained == 0


def test_the_checks_keep_the_runs_limits() -> None:
    # [0013.13] The limits given to the run hold for the checks as well as for the requests.
    version = late(0.6, b'{"version": "0.6.2"}')
    with ScriptedOllama(version, TAGS, answer("Late.")) as ollama:
        run = explain([subject(0)], env_for(ollama.address), limits=Limits(check_seconds=0.3))
    assert ollama.paths() == CHECKS[:1]
    assert run.unavailable is not None
    assert run.unavailable.reason is Unavailable.TIMEOUT
    assert run.explained == ()


@pytest.mark.parametrize(
    ("script", "reason", "asked"),
    [
        ([as_json({}, 404)], Unavailable.NOT_OLLAMA, CHECKS[:1]),
        ([VERSION, as_json({"models": []})], Unavailable.MODEL_MISSING, CHECKS),
    ],
)
def test_failed_checks_ask_for_no_explanation(
    script: list[Answer], reason: Unavailable, asked: list[tuple[str, str]]
) -> None:
    # [0013.13]
    with ScriptedOllama(*script) as ollama:
        run = explain([subject(n) for n in range(25)], env_for(ollama.address))
    assert ollama.paths() == asked
    assert (run.model, run.explained, run.not_explained) == ("llama3.2", (), 5)
    assert run.unavailable is not None
    assert run.unavailable.reason is reason


def test_a_refused_setting_connects_nowhere(monkeypatch: pytest.MonkeyPatch) -> None:
    # [0013.13]
    connected = spy_on_connect(monkeypatch)
    run = explain([subject(0)], {"KRESORTER_OLLAMA_URL": "http://192.0.2.1:11434"})
    assert run.unavailable is not None
    assert run.unavailable.reason is Unavailable.CONFIG
    assert (run.model, run.explained, connected) == (None, (), [])


def spy_on_connect(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    connected: list[object] = []
    connect = socket.socket.connect

    def spy(sock: socket.socket, address: Any) -> None:
        connected.append(address)
        connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", spy)
    return connected


@pytest.mark.parametrize("env", [{}, {"KRESORTER_OLLAMA_URL": "https://example.com"}])
def test_nothing_to_explain_opens_no_connection(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    # [0013.13] Not even the checks, and no setting is read: nothing is missing either.
    connected = spy_on_connect(monkeypatch)
    with ScriptedOllama(VERSION, TAGS) as ollama:
        run = explain([], env | {"KRESORTER_OLLAMA_MODEL": "?"})
    assert (ollama.connections, connected) == (0, [])
    assert run == Explanations(model=None, explained=(), not_explained=0, unavailable=None)


def test_nothing_to_explain_leaves_a_working_ollama_alone() -> None:
    # [0013.13] The setting is valid and Ollama answers, yet with no subject nothing is asked.
    with ScriptedOllama(VERSION, TAGS) as ollama:
        run = explain([], env_for(ollama.address))
    assert ollama.connections == 0
    assert run == Explanations(model=None, explained=(), not_explained=0, unavailable=None)
