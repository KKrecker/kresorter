"""LM Studio, the second local server (decision 0019, items 6-9 and 14).

Exactly two requests, ``GET /v1/models`` and ``POST /v1/chat/completions``, through the one
network point, with its deadlines, bounds and headers; an answer that is not exactly as
expected is a reason. The scripted server of 0013 item 29 plays LM Studio, its answers LM
Studio's (``support.lmstudio``).
"""

import ast
import contextlib
import json
import re
import socket
from collections.abc import Callable
from pathlib import Path

import pytest

from kresorter import __version__
from kresorter.llm import lmstudio
from kresorter.llm.client import Status, generate, status
from kresorter.llm.failure import ExplanationUnavailable, Unavailable
from kresorter.llm.prompt import Facts, Language, instruction
from kresorter.llm.settings import Address
from kresorter.llm.transport import Limits
from support.lmstudio import CHAT, EMBEDDING, LISTED, MODEL, MODELS, completed, env_for, models
from support.ollama import (
    TAGS,
    VERSION,
    Answer,
    ScriptedOllama,
    after,
    as_json,
    body,
    head,
    raw,
    redirect,
)

SRC = Path(__file__).resolve().parents[2] / "src"
SUBJECT: Facts = {"kind": "finding", "level": "review", "reasons": ["large"], "extension": ".pdf"}


def ask(address: Address, subject: Facts = SUBJECT, *, language: Language = "en") -> str:
    return generate(address, MODEL, subject, server="lmstudio", language=language)


def failure(call: Callable[[], object]) -> ExplanationUnavailable:
    with pytest.raises(ExplanationUnavailable) as caught:
        call()
    assert caught.value.detail != ""
    return caught.value


def stopped(result: Status) -> Unavailable:
    assert result.failure is not None
    assert result.failure.detail != ""
    return result.failure.reason


def free_address() -> Address:
    with socket.create_server(("127.0.0.1", 0)) as taken:
        return Address("127.0.0.1", taken.getsockname()[1])


# --- status: the settings, then the models listed [0019.7] [0019.9] ------------------------------


def test_status_when_the_model_named_is_listed() -> None:
    # [0019.7] [0019.9] one request; LM Studio says no version
    with ScriptedOllama(MODELS) as server:
        found = status(env_for(server.address, MODEL))
    assert found == Status(server.address, MODEL, None, True, None, (MODEL,), "lmstudio")
    assert found.running
    assert server.paths() == [LISTED]


def test_without_a_model_named_the_first_that_is_not_an_embedding_model_is_taken() -> None:
    # [0019.7] nor one whose id is not a model's name; the window's choice lists the rest
    listed = models(EMBEDDING, "nomic-EMBED-x", "not a name", "llama-3.2-1b-instruct", MODEL)
    with ScriptedOllama(listed) as server:
        found = status(env_for(server.address))
    assert found == Status(
        server.address,
        "llama-3.2-1b-instruct",
        None,
        True,
        None,
        ("not a name", "llama-3.2-1b-instruct", MODEL),
        "lmstudio",
    )


@pytest.mark.parametrize("listed", [models(), models(EMBEDDING), models("text-embedding-3")])
def test_without_a_model_named_and_none_listed_the_model_is_missing(listed: Answer) -> None:
    # [0019.9] as when the model named is not listed: LM Studio runs, with no model to use
    with ScriptedOllama(listed) as server:
        found = status(env_for(server.address))
    assert stopped(found) is Unavailable.MODEL_MISSING
    assert (found.model, found.installed, found.running) == (None, False, True)
    assert found.models == ()


@pytest.mark.parametrize(
    "model", ["qwen2.5-7b", "Qwen2.5-7b-instruct", "qwen2.5-7b-instruct@q4_k_m", "qwen2.5-7b-"]
)
def test_a_model_is_available_when_listed_exactly(model: str) -> None:
    # [0019.7] no tag added, no case folded
    with ScriptedOllama(MODELS) as server:
        found = status(env_for(server.address, model))
    assert stopped(found) is Unavailable.MODEL_MISSING
    assert (found.model, found.installed, found.models) == (model, False, (MODEL,))
    with ScriptedOllama(models(f"{MODEL}@q4_k_m")) as server:
        assert status(env_for(server.address, f"{MODEL}@q4_k_m")).installed is True


@pytest.mark.parametrize(
    "answer",
    [
        as_json({"error": "Unexpected endpoint"}, 404),
        as_json({}, 500),
        body(b"<html>LM Studio</html>"),
        body(b"\xff\xfe"),
        as_json([{"id": MODEL}]),
        as_json({}),
        as_json({"object": "list"}),
        as_json({"data": {"id": MODEL}}),
        as_json({"data": [MODEL]}),
        as_json({"data": [{"name": MODEL}]}),
        as_json({"data": [{"id": 7}]}),
        as_json({"data": [{"id": MODEL}, {"id": None}]}),
        as_json({"version": "0.6.2"}),
        as_json({"models": [{"name": "llama3.2:latest"}]}),
        raw(b"not HTTP at all\r\n\r\n"),
    ],
)
def test_what_does_not_answer_models_as_lm_studio(answer: Answer) -> None:
    # [0019.9] not_lmstudio, a reason of its own; nothing else is asked
    with ScriptedOllama(answer) as server:
        found = status(env_for(server.address, MODEL))
    assert stopped(found) is Unavailable.NOT_LMSTUDIO
    assert (found.address, found.model, found.installed, found.running) == (
        server.address,
        MODEL,
        None,
        False,
    )
    assert server.paths() == [LISTED]


def test_nothing_listening_is_unreachable() -> None:
    # [0019.9] the transport's reasons are LM Studio's too
    found = status(env_for(free_address()))
    assert stopped(found) is Unavailable.UNREACHABLE
    assert not found.running


def test_a_redirect_is_not_followed() -> None:
    # [0019.9]
    with ScriptedOllama(redirect("http://127.0.0.1:1/v1/models")) as server:
        assert stopped(status(env_for(server.address))) is Unavailable.REDIRECT
    assert server.connections == 1


def test_the_models_are_asked_under_the_check_deadline() -> None:
    # [0019.9] 0013 item 12's deadline for a check
    data = json.dumps({"data": [{"id": MODEL}]}).encode()
    with ScriptedOllama(after(1.0, head(200, length=len(data)) + data)) as server:
        found = status(env_for(server.address), limits=Limits(check_seconds=0.2))
    assert stopped(found) is Unavailable.TIMEOUT


def test_an_answer_over_the_limit_is_too_large() -> None:
    # [0019.9] 0013 item 12's bound
    with ScriptedOllama(models(*(f"model-{n:05d}" for n in range(2000)))) as server:
        found = status(env_for(server.address), limits=Limits(answer_bytes=4096))
    assert stopped(found) is Unavailable.TOO_LARGE


@pytest.mark.parametrize(
    ("more", "address_kept"),
    [
        ({"KRESORTER_LLM_SERVER": "LM Studio"}, False),
        ({"KRESORTER_LMSTUDIO_URL": "http://10.0.0.1:1234"}, False),
        ({"KRESORTER_LMSTUDIO_MODEL": "a b"}, True),
    ],
)
def test_a_refused_setting_sends_nothing(more: dict[str, str], address_kept: bool) -> None:
    # [0019.5] [0019.6] [0019.7]
    with ScriptedOllama(MODELS) as server:
        found = status({**env_for(server.address), **more})
    assert stopped(found) is Unavailable.CONFIG
    assert found.address == (server.address if address_kept else None)
    assert (found.model, found.installed, found.running) == (None, None, False)
    assert server.connections == 0


def test_ollama_is_checked_unless_the_server_is_lm_studio() -> None:
    # [0019.5] Ollama's two checks, and a status that says Ollama
    with ScriptedOllama(VERSION, TAGS) as server:
        found = status(
            {"KRESORTER_OLLAMA_URL": server.address.url, "KRESORTER_LLM_SERVER": "ollama"}
        )
    assert (found.server, found.version, found.installed, found.running) == (
        "ollama",
        "0.6.2",
        True,
        True,
    )
    assert server.paths() == [("GET", "/api/version"), ("GET", "/api/tags")]
    with ScriptedOllama(as_json({"version": "0.6.2"}), as_json({}, 500)) as server:
        tags_failed = status({"KRESORTER_OLLAMA_URL": server.address.url})
    assert (tags_failed.server, tags_failed.running) == ("ollama", True)


# --- exactly two requests [0019.8] ---------------------------------------------------------------


def test_the_two_requests_are_pinned() -> None:
    # [0019.8]
    assert lmstudio.REQUESTS == (LISTED, CHAT) == (lmstudio.MODELS, lmstudio.CHAT)


def test_no_flow_sends_another_request() -> None:
    # [0019.8] never one that downloads, loads or unloads a model
    flows: list[tuple[list[Answer], Callable[[Address], object]]] = [
        ([MODELS], lambda address: status(env_for(address))),
        ([models()], lambda address: status(env_for(address))),
        ([as_json({}, 404)], lambda address: status(env_for(address, MODEL))),
        ([completed("A PDF document.")], ask),
        ([as_json({"error": "model not loaded"}, 404)], ask),
        ([completed("")], ask),
    ]
    sent: list[tuple[str, str]] = []
    for script, flow in flows:
        with ScriptedOllama(*script) as server, contextlib.suppress(ExplanationUnavailable):
            flow(server.address)
        sent += server.paths()
    assert set(sent) == set(lmstudio.REQUESTS)


def test_no_other_path_of_lm_studios_api_is_named_in_src() -> None:
    # [0019.8] /v1/embeddings, /v1/completions, LM Studio's /api/v0: never named, never sent
    named = {
        found
        for path in sorted(SRC.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        for found in re.findall(r"/v[0-9]+/[\w/]*", node.value)
    }
    assert named == {"/v1/models", "/v1/chat/completions"}


def test_the_headers_sent() -> None:
    # [0019.8] those of 0013 item 11
    with ScriptedOllama(MODELS, completed("A PDF document.")) as server:
        status(env_for(server.address))
        ask(server.address)
    common = [
        ("host", f"127.0.0.1:{server.address.port}"),
        ("accept-encoding", "identity"),
        ("user-agent", f"kresorter/{__version__}"),
        ("accept", "application/json"),
        ("connection", "close"),
    ]
    listed, chat = server.received
    assert sorted((name.lower(), value) for name, value in listed.headers) == sorted(common)
    assert listed.body == b""
    posted = [
        *common,
        ("content-type", "application/json"),
        ("content-length", str(len(chat.body))),
    ]
    assert sorted((name.lower(), value) for name, value in chat.headers) == sorted(posted)


@pytest.mark.parametrize("language", ["en", "ru"])
def test_an_explanations_body(language: Language) -> None:
    # [0019.8] exactly these fields, in this order; the subject as JSON, its facts in order
    with ScriptedOllama(completed("A PDF document.")) as server:
        ask(server.address, language=language)
    [chat] = server.received
    assert (chat.method, chat.path) == CHAT
    sent = json.loads(chat.body)
    assert list(sent) == ["model", "messages", "temperature", "seed", "max_tokens", "stream"]
    assert sent == {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": instruction(language)},
            {"role": "user", "content": json.dumps(SUBJECT, ensure_ascii=False)},
        ],
        "temperature": 0,
        "seed": 0,
        "max_tokens": 200,
        "stream": False,
    }
    assert [list(message) for message in sent["messages"]] == [["role", "content"]] * 2


def test_a_chat_body() -> None:
    # [0019.8] a response format, when asked, after stream
    sent = json.loads(lmstudio.chat_body("m", "Be brief.", "Hi ж", max_tokens=9))
    assert list(sent) == ["model", "messages", "temperature", "seed", "max_tokens", "stream"]
    assert sent["max_tokens"] == 9
    shaped = lmstudio.chat_body("m", "s", "u", max_tokens=1, response_format={"type": "text"})
    assert list(json.loads(shaped))[-2:] == ["stream", "response_format"]
    assert "ж".encode() in lmstudio.chat_body("m", "s", "ж", max_tokens=1)


# --- what is accepted of an answer [0019.9] ------------------------------------------------------


def test_the_accepted_answer_is_the_first_choices_message() -> None:
    # [0019.9] cleaned (0013 item 20); other choices and fields are not read
    second = {"index": 1, "message": {"role": "assistant", "content": "Another."}}
    cache = "\x1b[31mThe cache\x1b[0m of pip.\r\n\n\t\u202eSafe to clear."
    first = {"index": 0, "message": {"role": "assistant", "content": cache}}
    with ScriptedOllama(completed("x", choices=[first, second], usage=None)) as server:
        assert ask(server.address) == "The cache of pip.\nSafe to clear."


def test_a_reasoning_models_thinking_is_not_the_answer() -> None:
    # [0019.9] [0019.2]
    with ScriptedOllama(completed("<think>It is a PDF.</think>\nA PDF document.")) as server:
        assert ask(server.address) == "A PDF document."


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (as_json({"error": "model not loaded"}, 404), Unavailable.HTTP_STATUS),
        (as_json({"error": "boom"}, 500), Unavailable.HTTP_STATUS),
        (body(b"not json"), Unavailable.BAD_RESPONSE),
        (as_json([]), Unavailable.BAD_RESPONSE),
        (as_json({}), Unavailable.BAD_RESPONSE),
        (completed("x", choices={}), Unavailable.BAD_RESPONSE),
        (completed("x", choices=[]), Unavailable.BAD_RESPONSE),
        (completed("x", choices=["A PDF."]), Unavailable.BAD_RESPONSE),
        (completed("x", choices=[{"text": "A PDF."}]), Unavailable.BAD_RESPONSE),
        (completed("x", choices=[{"message": "A PDF."}]), Unavailable.BAD_RESPONSE),
        (completed(None), Unavailable.BAD_RESPONSE),
        (completed(["A PDF."]), Unavailable.BAD_RESPONSE),
        (as_json({"response": "A PDF.", "done": True}), Unavailable.BAD_RESPONSE),
        (completed(""), Unavailable.EMPTY),
        (completed("<think>Only this.</think>"), Unavailable.EMPTY),
        (redirect("http://127.0.0.1:1/"), Unavailable.REDIRECT),
    ],
)
def test_anything_else_is_refused(answer: Answer, reason: Unavailable) -> None:
    # [0019.9] [0013.23]
    with ScriptedOllama(answer) as server:
        assert failure(lambda: ask(server.address)).reason is reason


def test_an_explanation_has_its_deadline() -> None:
    # [0019.9] 0013 item 12's deadline for an answer, not the check's
    data = json.dumps({"choices": [{"message": {"content": "Late."}}]}).encode()
    late = after(0.5, head(200, length=len(data)) + data)
    with ScriptedOllama(late) as server:
        quick = Limits(check_seconds=0.1, generate_seconds=0.2)
        found = failure(
            lambda: generate(server.address, MODEL, SUBJECT, server="lmstudio", limits=quick)
        )
    assert found.reason is Unavailable.TIMEOUT
    with ScriptedOllama(late) as server:
        slow = Limits(check_seconds=0.1, generate_seconds=3.0)
        assert generate(server.address, MODEL, SUBJECT, server="lmstudio", limits=slow) == "Late."
