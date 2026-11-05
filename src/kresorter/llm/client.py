"""Ollama's three requests: what ``status`` checks, the one answer taken (decision 0013); and,
when the settings name LM Studio, LM Studio's two (``llm.lmstudio``, decision 0019).

Items 11, 14, 19 and 23. ``version`` and ``tags`` run under the check deadline, ``generate``
under its own (item 12). An answer that is not exactly as expected is a reason, never a guess.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from kresorter.llm import lmstudio
from kresorter.llm.clean import cleaned_answer, without_thinking
from kresorter.llm.failure import ExplanationUnavailable, Unavailable
from kresorter.llm.prompt import Facts, Language, chat_body, generate_body
from kresorter.llm.settings import (
    Address,
    Server,
    address_from,
    installed,
    model_from,
    server_from,
)
from kresorter.llm.transport import LIMITS, Asked, Limits, json_of, request

__all__ = [
    "GENERATE",
    "REQUESTS",
    "TAGS",
    "VERSION",
    "Asked",
    "Status",
    "answered",
    "generate",
    "generated",
    "status",
]

VERSION: Asked = ("GET", "/api/version")
TAGS: Asked = ("GET", "/api/tags")
GENERATE: Asked = ("POST", "/api/generate")
REQUESTS = (VERSION, TAGS, GENERATE)

_VERSION = re.compile(r"[0-9A-Za-z.+-]{1,32}", re.ASCII)


@dataclass(frozen=True)
class Status:
    """What ``status`` found, in item 14's order; ``None`` where it did not get that far. LM
    Studio has no version; its model, when none is named, is the first it lists."""

    address: Address | None
    model: str | None
    version: str | None
    installed: bool | None
    failure: ExplanationUnavailable | None
    models: tuple[str, ...] = ()  # those listed, for the window's choice (0018 item 32)
    server: Server = "ollama"

    @property
    def running(self) -> bool:
        """The server answered as itself: Ollama its version, LM Studio its models."""
        return self.version is not None or self.installed is not None


def status(env: Mapping[str, str], *, limits: Limits = LIMITS) -> Status:
    """The settings, then Ollama's ``version`` and ``tags``, or LM Studio's models: each only
    if the previous one passed."""
    try:
        server = server_from(env)
    except ExplanationUnavailable as refused:
        return Status(None, None, None, None, refused)
    try:
        address = address_from(env)
    except ExplanationUnavailable as refused:
        return Status(None, None, None, None, refused, server=server)
    try:
        model = model_from(env)
    except ExplanationUnavailable as refused:
        return Status(address, None, None, None, refused, server=server)
    version = None
    try:
        if server == "lmstudio":
            names = lmstudio.models(address, limits)
        else:
            version = _version(address, limits)
            names = _names(address, limits)
    except ExplanationUnavailable as failed:
        return Status(address, model, version, None, failed, server=server)
    if server == "lmstudio":
        return _listed(address, model, names)
    return _installed(address, model, version, names)


def _installed(
    address: Address, model: str | None, version: str | None, names: list[str]
) -> Status:
    """Ollama's model among those it lists, by its name or with ``:latest``."""
    if model is None or not installed(model, names):
        missing = ExplanationUnavailable(
            Unavailable.MODEL_MISSING, f"{model!r} is not among the {len(names)} models listed"
        )
        return Status(address, model, version, False, missing, tuple(names))
    return Status(address, model, version, True, None, tuple(names))


def _listed(address: Address, model: str | None, ids: list[str]) -> Status:
    """LM Studio's model, named or the first it lists, among those it lists, exactly."""
    chosen = model if model is not None else lmstudio.first(ids)
    listed = tuple(lmstudio.chat_models(ids))
    if chosen is None:
        none = ExplanationUnavailable(
            Unavailable.MODEL_MISSING, f"none of the {len(ids)} models listed is a chat model"
        )
        return Status(address, None, None, False, none, listed, "lmstudio")
    if chosen not in ids:
        missing = ExplanationUnavailable(
            Unavailable.MODEL_MISSING, f"{chosen!r} is not among the {len(ids)} models listed"
        )
        return Status(address, chosen, None, False, missing, listed, "lmstudio")
    return Status(address, chosen, None, True, None, listed, "lmstudio")


def generate(
    address: Address,
    model: str,
    subject: Facts,
    *,
    server: Server = "ollama",
    language: Language = "en",
    limits: Limits = LIMITS,
) -> str:
    """One explanation of one subject, in ``language``, cleaned (item 20); any other answer is
    a reason."""
    if server == "lmstudio":
        body = chat_body(model, subject, language)
    else:
        body = generate_body(model, subject, language)
    answer = answered(server, address, body, seconds=limits.generate_seconds, limits=limits)
    text = cleaned_answer(answer)
    if not text:
        raise ExplanationUnavailable(Unavailable.EMPTY, "nothing left once cleaned")
    return text


def answered(
    server: Server, address: Address, body: bytes, *, seconds: float, limits: Limits
) -> str:
    """The text of one finished answer to ``body``: Ollama's generate, LM Studio's chat."""
    if server == "lmstudio":
        return lmstudio.chatted(address, body, seconds=seconds, limits=limits)
    return generated(address, body, seconds=seconds, limits=limits)


def generated(address: Address, body: bytes, *, seconds: float, limits: Limits) -> str:
    """The text of one finished answer to ``POST /api/generate`` with ``body``, as it came but
    for the thinking it starts with; any other answer is a reason."""
    method, path = GENERATE
    answer = request(address, method, path, body, seconds=seconds, limits=limits)
    if answer.status != 200:
        raise ExplanationUnavailable(
            Unavailable.HTTP_STATUS, f"{method} {path}: status {answer.status}"
        )
    value = json_of(answer.body)
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


def _checked(address: Address, asked: Asked, limits: Limits) -> dict[str, object]:
    method, path = asked
    answer = request(address, method, path, seconds=limits.check_seconds, limits=limits)
    if answer.status != 200:
        raise _not_ollama(asked, f"status {answer.status}")
    value = json_of(answer.body)
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
