"""The model's answer, made safe to print (decision 0013, item 20).

Escape sequences go whole, tabs become spaces, then the characters of the categories item 20
lists; lines are stripped, empty ones dropped; at most 6 lines and 600 characters are kept,
ending with an ellipsis when cut. What is removed is listed here, not taken from the code.
"""

import random
import unicodedata

import pytest

from safeclean.llm.clean import cleaned_answer

REMOVED = frozenset({"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp"})


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("\x1b[31mred\x1b[0m text", "red text"),
        ("\x1b[2J\x1b[HMoved 3 files", "Moved 3 files"),
        ("\x1b[38;2;255;0;0mtrue colour\x1b[m", "true colour"),
        ("\x1b[?25lhidden cursor\x1b[?25h", "hidden cursor"),
        ("\x1b[1Aup a line", "up a line"),
        ("\x1b]0;owned\x07title", "title"),
        ("\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\", "link"),
        ("\x1b]52;c;cm0gLXJmIH4=\x07clipboard", "clipboard"),
        ("\x1b]0;title\x1b[31mred", "red"),
        ("\x1bP+q544e\x1b\\dcs", "dcs"),
        ("\x1b_apc\x1b\\after", "after"),
        ("\x1b^pm\x07after", "after"),
        ("\x1b(Bcharset", "charset"),
        ("\x1bcreset", "reset"),
        ("\x1b7saved\x1b8", "saved"),
        ("unterminated \x1b]0;title", "unterminated"),
        ("end\x1b", "end"),
        ("\x9b2Jc1", "2Jc1"),
    ],
)
def test_escape_sequences_are_removed_whole(text: str, shown: str) -> None:
    # [0013.20] An 8-bit CSI is one control character: it goes, what follows is plain text.
    assert cleaned_answer(text) == shown


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("safe\u202eevil", "safeevil"),
        ("zero\u200bwidth", "zerowidth"),
        ("bom\ufeff", "bom"),
        ("tag\U000e0041s", "tags"),
        ("nul\x00bel\x07", "nulbel"),
        ("Safe\rDanger", "SafeDanger"),
        ("vt\x0bff\x0c", "vtff"),
        ("nel\x85", "nel"),
        ("del\x7f", "del"),
        ("line\u2028sep", "linesep"),
        ("para\u2029sep", "parasep"),
        ("priv\ue000ate", "private"),
        ("plane\U000f0000", "plane"),
        ("un\u0378assigned", "unassigned"),
        ("non\uffffchar", "nonchar"),
        ("lone\ud800", "lone"),
        ("a\tb\t\tc", "a b  c"),
    ],
)
def test_control_and_invisible_characters_are_removed(text: str, shown: str) -> None:
    # [0013.20]
    assert cleaned_answer(text) == shown


def test_what_is_printable_stays() -> None:
    # [0013.20]
    text = "café, e\u0301, a\u00a0b, “quotes”, 日本語, 🙂, ½ & <tags>"
    assert cleaned_answer(text) == text


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("  first  \n\n\n  second\t\n \n", "first\nsecond"),
        ("one\r\ntwo\r\n", "one\ntwo"),
        ("\n\n\x1b[2J\nonly\n\u200b\n", "only"),
    ],
)
def test_lines_are_stripped_and_empty_ones_dropped(text: str, shown: str) -> None:
    # [0013.20]
    assert cleaned_answer(text) == shown


def lines(count: int, width: int = 6) -> list[str]:
    return [f"{n:<{width - 1}}." for n in range(1, count + 1)]


def test_at_most_six_lines() -> None:
    # [0013.20]
    six = "\n".join(lines(6))
    assert cleaned_answer(six) == six
    assert cleaned_answer("\n".join(lines(7))) == six + "…"
    assert cleaned_answer("\n\n".join(lines(9))) == six + "…"


def test_at_most_600_characters() -> None:
    # [0013.20]
    assert cleaned_answer("a" * 600) == "a" * 600
    assert cleaned_answer("a" * 601) == "a" * 599 + "…"
    assert cleaned_answer("a" * 700) == "a" * 599 + "…"
    full = "\n".join([*lines(5, 99), "b" * 100])  # six lines, 600 characters with newlines
    assert cleaned_answer(full) == full
    cut = cleaned_answer(full + "\nseventh")
    assert (len(cut), cut[-1], cut[:-1]) == (600, "…", full[:599])


def test_nothing_unsafe_survives() -> None:
    # [0013.20] Random mixtures, the same every run: no escape, no listed category, within bounds,
    # and cleaning again changes nothing.
    pieces = [
        *"\x1b[]P\\_^()7c;?0123456789mJH\x07\x9b\x9d\x00\x7f\x85\r\t\n  aZé…",
        "\u202e",
        "\u200b",
        "\u2028",
        "\u2029",
        "\ufeff",
        "\ue000",
        "\ud800",
        "\u0378",
        "\U000e0041",
    ]
    rng = random.Random(13)
    for _ in range(2000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randrange(900)))
        shown = cleaned_answer(text)
        assert "\x1b" not in shown
        assert all(c == "\n" or unicodedata.category(c) not in REMOVED for c in shown)
        assert len(shown) <= 600
        assert shown == "" or all(line and line == line.strip() for line in shown.split("\n"))
        assert len(shown.split("\n")) <= 6
        assert cleaned_answer(shown) == shown
