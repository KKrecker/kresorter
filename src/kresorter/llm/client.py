"""Ollama's three requests: what ``status`` checks, the one answer taken (decision 0013).

Items 11, 14, 19 and 23. ``version`` and ``tags`` run under the check deadline, ``generate``
under its own (item 12). An answer that is not exactly as expected is a reason, never a guess.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from kresorter.llm.clean import cleaned_answer, without_thinking
from kresorter.llm.failure import ExplanationUnavailable, Unavailable
from kresorter.llm.prompt import Facts, Language, generate_body
from kresorter.llm.settings import Address, address_from, installed, model_from
from kresorter.llm.transport import LIMITS, Limits, request

Asked = tuple[Literal["GET", "POST"], str]

VERSION: Asked = ("GET", "/api/version")
TAGS: Asked = ("GET", "/api/tags")
GENERATE: Asked = ("POST", "/api/generate")
REQUESTS = (VERSION, TAGS, GENERATE)

_VERSION = re.compile(r"[0-9A-Za-z.+-]{1,32}", re.ASCII)


@dataclass(frozen=True)
class Status:
    """What ``status`` found, in item 14's order; ``None`` where it did not get that far."""

    address: Address | None
    model: str | None
    version: str | None
    installed: bool | None
    failure: ExplanationUnavailable | None
    models: tuple[str, ...] = ()  # those Ollama listed, for the window's choice (0018 item 32)


def status(env: Mapping[str, str], *, limits: Limits = LIMITS) -> Status:
    """The settings, then ``version``, then ``tags``: each only if the previous one passed."""
    try:
        address = address_from(env)
    except ExplanationUnavailable as refused:
        return Status(None, None, None, None, refused)
    try:
        model = model_from(env)
    except ExplanationUnavailable as refused:
        return Status(address, None, None, None, refused)
    try:
        version = _version(address, limits)
    except ExplanationUnavailable as failed:
        return Status(address, model, None, None, failed)
    try:
        names = _names(address, limits)
    except ExplanationUnavailable as failed:
        return Status(address, model, version, None, failed)
    if not installed(model, names):
        missing = ExplanationUnavailable(
            Unavailable.MODEL_MISSING, f"{model!r} is not among the {len(names)} models listed"
        )
        return Status(address, model, version, False, missing, tuple(names))
    return Status(address, model, version, True, None, tuple(names))


def generate(
    address: Address,
    model: str,
    subject: Facts,
    *,
    language: Language = "en",
    limits: Limits = LIMITS,
) -> str:
    """One explanation of one subject, in ``language``, cleaned (item 20); any other answer is
    a reason."""
    body = generate_body(model, subject, language)
    text = cleaned_answer(generated(address, body, seconds=limits.generate_seconds, limits=limits))
    if not text:
        raise ExplanationUnavailable(Unavailable.EMPTY, "nothing left once cleaned")
    return text


def generated(address: Address, body: bytes, *, seconds: float, limits: Limits) -> str:
    """The text of one finished answer to ``POST /api/generate`` with ``body``, as it came but
    for the thinking it starts with; any other answer is a reason."""
    method, path = GENERATE
    answer = request(address, method, path, body, seconds=seconds, limits=limits)
    if answer.status != 200:
        raise ExplanationUnavailable(
            Unavailable.HTTP_STATUS, f"{method} {path}: status {answer.status}"
        )
    value = _json(answer.body)
    if not isinstance(value, dict) or value.get("done") is not True:
        raise ExplanationUnavailable(
            Unavailable.BAD_RESPONSE, f"{method} {path}: not a finished answer"
        )
    response = value.get("response")
    if not isinstance(response, str):
        raise ExplanationUnavailable(
            Unavailable.BAD_RESPONSE, f"{method} {path}: no text in the answer"
        )
    return without_thinking(response)


def _not_ollama(asked: Asked, why: str) -> ExplanationUnavailable:
    return ExplanationUnavailable(Unavailable.NOT_OLLAMA, f"{asked[0]} {asked[1]}: {why}")


def _json(data: bytes) -> object:
    """The JSON value of a UTF-8 body, or ``None`` for anything else."""
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None


def _checked(address: Address, asked: Asked, limits: Limits) -> dict[str, object]:
    method, path = asked
    answer = request(address, method, path, seconds=limits.check_seconds, limits=limits)
    if answer.status != 200:
        raise _not_ollama(asked, f"status {answer.status}")
    value = _json(answer.body)
    if not isinstance(value, dict):
        raise _not_ollama(asked, "not a JSON object")
    return value


def _version(address: Address, limits: Limits) -> str:
    version = _checked(address, VERSION, limits).get("version")
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise _not_ollama(VERSION, "no version of 1-32 letters, digits, '.', '+' or '-'")
    return version


def _names(address: Address, limits: Limits) -> list[str]:
    models = _checked(address, TAGS, limits).get("models")
    if not isinstance(models, list):
        raise _not_ollama(TAGS, "no list of models")
    names: list[str] = []
    for model in models:
        name = model.get("name") if isinstance(model, dict) else None
        if not isinstance(name, str):
            raise _not_ollama(TAGS, "a model without a name")
        names.append(name)
    return names
