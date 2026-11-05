"""LM Studio's answers, for the scripted server of 0013 item 29 (decision 0019, item 14): what
``GET /v1/models`` and ``POST /v1/chat/completions`` answer, as LM Studio's OpenAI-compatible
API answers them, and the settings that point kresorter at the script."""

from __future__ import annotations

from kresorter.llm.settings import Address
from support.ollama import Answer, as_json

MODEL = "qwen2.5-7b-instruct"
EMBEDDING = "text-embedding-nomic-embed-text-v1.5"
LISTED = ("GET", "/v1/models")
CHAT = ("POST", "/v1/chat/completions")


def models(*ids: object) -> Answer:
    """``/v1/models``: each id an object of the list LM Studio gives."""
    data = [{"id": one, "object": "model", "owned_by": "organization_owner"} for one in ids]
    return as_json({"data": data, "object": "list"})


MODELS = models(EMBEDDING, MODEL)


def completed(content: object, finish_reason: str = "stop", **fields: object) -> Answer:
    """``/v1/chat/completions``, without streaming: ``content``, the first choice's message,
    ended for ``finish_reason``."""
    choice = {
        "index": 0,
        "logprobs": None,
        "finish_reason": finish_reason,
        "message": {"role": "assistant", "content": content},
    }
    answer = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1762300000,
        "model": MODEL,
        "choices": [choice],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        "stats": {},
        "system_fingerprint": MODEL,
    }
    return as_json(answer | fields)


def env_for(address: Address, model: str | None = None, **more: str) -> dict[str, str]:
    """kresorter's settings for LM Studio at ``address``, with ``model`` named if given."""
    env = {"KRESORTER_LLM_SERVER": "lmstudio", "KRESORTER_LMSTUDIO_URL": address.url, **more}
    if model is not None:
        env["KRESORTER_LMSTUDIO_MODEL"] = model
    return env
