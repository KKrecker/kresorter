"""LM Studio's two requests (decision 0019, items 7-9): the models it lists, one chat
completion; never one that downloads, loads or unloads a model.

``models`` runs under the check deadline, a chat under the deadline its caller gives. An answer
that is not exactly as expected is a reason, never a guess: from ``/v1/models``,
``not_lmstudio``; from ``/v1/chat/completions``, ``http_status`` or ``bad_response``.
"""

import json
from collections.abc import Iterable, Mapping

from kresorter.llm.clean import without_thinking
from kresorter.llm.failure import ExplanationUnavailable, Unavailable
from kresorter.llm.settings import Address, is_model_name
from kresorter.llm.transport import Asked, Limits, json_of, request

__all__ = ["CHAT", "MODELS", "REQUESTS", "chat_body", "chat_models", "chatted", "first", "models"]

MODELS: Asked = ("GET", "/v1/models")
CHAT: Asked = ("POST", "/v1/chat/completions")
REQUESTS = (MODELS, CHAT)


def chat_body(
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: int,
    response_format: Mapping[str, object] | None = None,
) -> bytes:
    """The body of ``POST /v1/chat/completions``: these fields, in this order, nothing else;
    ``response_format`` after ``stream`` when given."""
    body: dict[str, object] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "seed": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if response_format is not None:
        body["response_format"] = response_format
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def models(address: Address, limits: Limits) -> list[str]:
    """The id of each model ``/v1/models`` lists, in its order."""
    method, path = MODELS
    answer = request(
        address,
        method,
        path,
        seconds=limits.check_seconds,
        limits=limits,
        foreign=Unavailable.NOT_LMSTUDIO,
    )
    if answer.status != 200:
        raise _not_lmstudio(f"status {answer.status}")
    value = json_of(answer.body)
    data = value.get("data") if isinstance(value, dict) else None
    if not isinstance(data, list):
        raise _not_lmstudio("no list of models")
    ids: list[str] = []
    for model in data:
        found = model.get("id") if isinstance(model, dict) else None
        if not isinstance(found, str):
            raise _not_lmstudio("a model without an id")
        ids.append(found)
    return ids


def chat_models(ids: Iterable[str]) -> list[str]:
    """Those that are not embedding models: no ``embed`` in their id, in any case."""
    return [one for one in ids if "embed" not in one.lower()]


def first(ids: Iterable[str]) -> str | None:
    """The model taken when none is named: the first that is not an embedding model and whose
    id is a model's name."""
    return next((one for one in chat_models(ids) if is_model_name(one)), None)


def chatted(address: Address, body: bytes, *, seconds: float, limits: Limits) -> str:
    """The text of the first choice of one finished chat completion with ``body``, as it came
    but for the thinking it starts with; any other answer is a reason."""
    method, path = CHAT
    answer = request(
        address,
        method,
        path,
        body,
        seconds=seconds,
        limits=limits,
        foreign=Unavailable.NOT_LMSTUDIO,
    )
    if answer.status != 200:
        raise ExplanationUnavailable(
            Unavailable.HTTP_STATUS, f"{method} {path}: status {answer.status}"
        )
    value = json_of(answer.body)
    choices = value.get("choices") if isinstance(value, dict) else None
    chosen = choices[0] if isinstance(choices, list) and choices else None
    message = chosen.get("message") if isinstance(chosen, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ExplanationUnavailable(
            Unavailable.BAD_RESPONSE, f"{method} {path}: no text in the first choice"
        )
    return without_thinking(content)


def _not_lmstudio(why: str) -> ExplanationUnavailable:
    method, path = MODELS
    return ExplanationUnavailable(Unavailable.NOT_LMSTUDIO, f"{method} {path}: {why}")
