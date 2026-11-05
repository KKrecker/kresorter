"""Why an explanation is missing: a pinned set, each with a detail (decision 0013, item 23)."""

from enum import StrEnum


class Unavailable(StrEnum):
    CONFIG = "config"
    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"
    REDIRECT = "redirect"
    HTTP_STATUS = "http_status"
    NOT_OLLAMA = "not_ollama"
    NOT_LMSTUDIO = "not_lmstudio"  # decision 0019, item 9
    MODEL_MISSING = "model_missing"
    TOO_LARGE = "too_large"
    BAD_RESPONSE = "bad_response"
    EMPTY = "empty"


class ExplanationUnavailable(Exception):
    """No explanation, and why: the command goes on without one."""

    def __init__(self, reason: Unavailable, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class SettingRefused(ExplanationUnavailable):
    """A setting that is not used, always ``config``: its name, its value and why."""

    def __init__(self, name: str, value: str, why: str) -> None:
        super().__init__(Unavailable.CONFIG, f"{name}={value!r}: {why}")
        self.name = name
        self.value = value
        self.why = why
