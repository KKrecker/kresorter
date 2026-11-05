"""One run's explanations: the checks once, at most 20 requests, none after a failure.

Decision 0013, item 13. The subjects come in the order the command shows them (item 18). A run
with nothing to explain reads no setting and opens no connection.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from kresorter.llm.client import generate, status
from kresorter.llm.failure import ExplanationUnavailable
from kresorter.llm.prompt import Language
from kresorter.llm.subjects import Subject
from kresorter.llm.transport import LIMITS, Limits

BUDGET = 20


@dataclass(frozen=True)
class Explained:
    subject: Subject
    text: str  # cleaned (item 20)


@dataclass(frozen=True)
class Explanations:
    """What a run got: ``unavailable`` says why it got none, or why it stopped."""

    model: str | None  # None when nothing was checked or the setting was refused
    explained: tuple[Explained, ...]
    not_explained: int  # subjects beyond the budget
    unavailable: ExplanationUnavailable | None


def explain(
    subjects: Sequence[Subject],
    env: Mapping[str, str],
    *,
    language: Language = "en",
    limits: Limits = LIMITS,
    budget: int = BUDGET,
) -> Explanations:
    """Each subject in order, until the budget is spent or a request fails; each answer asked
    in ``language``, English as the console's (decision 0019, item 1)."""
    if not subjects:
        return Explanations(None, (), 0, None)
    left_out = max(0, len(subjects) - budget)
    checked = status(env, limits=limits)
    if checked.failure is not None or checked.address is None or checked.model is None:
        return Explanations(checked.model, (), left_out, checked.failure)
    explained: list[Explained] = []
    for subject in subjects[:budget]:
        try:
            text = generate(
                checked.address,
                checked.model,
                subject.facts,
                server=checked.server,
                language=language,
                limits=limits,
            )
        except ExplanationUnavailable as failed:
            return Explanations(checked.model, tuple(explained), left_out, failed)
        explained.append(Explained(subject, text))
    return Explanations(checked.model, tuple(explained), left_out, None)
