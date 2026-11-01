"""Text from the model and the facts sent to it, made safe (decision 0013, items 17, 20).

Escape sequences are removed whole first, so none is left half; then tabs become spaces and
every character of the listed categories goes, whatever a terminal would do with it. An
answer keeps its lines; a fact of a subject is one line.
"""

import re
import unicodedata

MAX_LINES = 6
MAX_CHARACTERS = 600
FACT_CHARACTERS = 100
ELLIPSIS = "…"

# A string sequence (OSC, DCS, SOS, PM, APC) ends at BEL, at ST, at the next ESC or at the end.
_STRING = r"\x1b[\]PX^_][^\x07\x1b]*(?:\x07|\x1b\\|(?=\x1b)|\Z)"
_CSI = r"\x1b\[[0-?]*[ -/]*[@-~]"
_OTHER = r"\x1b[ -/]*[0-~]"
_ESCAPES = re.compile(f"{_STRING}|{_CSI}|{_OTHER}")
_REMOVED = frozenset({"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp"})


def without_controls(text: str) -> str:
    """No escape sequence, tabs as spaces, no character of the removed categories but ``\\n``."""
    text = _ESCAPES.sub("", text).replace("\t", " ")
    return "".join(c for c in text if c == "\n" or unicodedata.category(c) not in _REMOVED)


def cut(text: str, limit: int) -> str:
    """At most ``limit`` characters, the last one an ellipsis when something was cut."""
    return text if len(text) <= limit else text[: limit - 1] + ELLIPSIS


def cleaned_answer(text: str) -> str:
    """At most 6 stripped, non-empty lines and 600 characters; empty when nothing is left."""
    lines = [line.strip() for line in without_controls(text).split("\n")]
    kept = [line for line in lines if line]
    shown = "\n".join(kept[:MAX_LINES])
    if len(kept) > MAX_LINES:
        return shown[: MAX_CHARACTERS - 1] + ELLIPSIS
    return cut(shown, MAX_CHARACTERS)


def one_line(text: str) -> str:
    """Cleaned as an answer is, its stripped non-empty lines joined by a space: one line."""
    return " ".join(line.strip() for line in without_controls(text).split("\n") if line.strip())


def cleaned_fact(text: str) -> str:
    """A fact of a subject (item 17): on one line and at most 100 characters."""
    return cut(one_line(text), FACT_CHARACTERS)
