"""The subject of an explanation: the facts of one result and nothing else (decision 0013).

Items 17 and 18. A subject is made from a final result by a pure function: ``kind`` first,
then a fixed, ordered list of facts per kind. Results with the same facts are one subject, in
the order they first appear. What the model could learn is what the scripted server receives.
"""

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from kresorter.analysis.report import Finding
from kresorter.analysis.score import Evidence, Level, Reason, junk_reason, level_of
from kresorter.autostart.models import AutostartItem, Scope, Source, entry_digest
from kresorter.core.heuristics import JunkMatch, JunkRule, default_rules
from kresorter.core.models import FileEntry
from kresorter.core.preflight import Candidate
from kresorter.llm.client import generate
from kresorter.llm.prompt import generate_body
from kresorter.llm.subjects import Result, subject_of, subjects
from kresorter.llm.transport import LIMITS
from kresorter.organize.planner import Stay, StayReason
from support.ollama import ScriptedOllama, as_json

FOLDER = Path("/home/alice/Secret-Project")
MTIME_NS = 1_700_000_000_123_456_789
DIGEST = "0f" * 32
LARGE = Reason(Evidence.LARGE, "5.0 GiB")
OLD = Reason(Evidence.OLD, "unmodified for 400 days")
PYCACHE = Reason(Evidence.JUNK_CACHE, "python-bytecode")


def entry(name: str, folder: Path = FOLDER) -> FileEntry:
    return FileEntry(folder / name, 5 << 30, MTIME_NS)


def finding(name: str = "report.PDF", *reasons: Reason) -> Finding:
    """A finding as analysis makes it: its level is that of its strongest reason."""
    file = entry(name)
    given = reasons or (LARGE, OLD)
    return Finding(file, level_of(given[0].evidence), given, Candidate(file), None)


ITEM = AutostartItem(
    source=Source.XDG_AUTOSTART,
    scope=Scope.USER,
    name="My App",
    command='"/opt/My App/bin/app" --token=SECRET',
    location="/home/alice/.config/autostart/my-app.desktop",
    enabled=True,
    digest=entry_digest(b'[Desktop Entry]\nExec="/opt/My App/bin/app" --token=SECRET\n'),
)


def item(**changes: Any) -> AutostartItem:
    return dataclasses.replace(ITEM, **changes)


def stay(name: str = "Movie.srt", reason: StayReason = StayReason.COMPANION) -> Stay:
    return Stay(FOLDER / "Downloads" / name, reason, "Movie.mkv")


# --- a finding [0013.17] -------------------------------------------------------------------------


def test_a_finding() -> None:
    # [0013.17] /home/alice/Secret-Project/report.PDF, large and old: these facts, in this order.
    facts = subject_of(finding()).facts
    assert facts == {
        "kind": "finding",
        "level": "review",
        "reasons": ("large", "old"),
        "extension": ".pdf",
    }
    assert list(facts) == ["kind", "level", "reasons", "extension"]


@pytest.mark.parametrize("rule", default_rules(), ids=lambda rule: rule.id)
def test_a_junk_reason_names_its_rule(rule: JunkRule) -> None:
    # [0013.17] Every rule kresorter ships: the evidence and the rule id, not what it matched.
    path = FOLDER / "__pycache__" / "secret.cpython-313.pyc"
    reason = junk_reason(JunkMatch(path, rule.id, rule.category, rule.description))
    facts = subject_of(finding("secret.cpython-313.pyc", reason, LARGE)).facts
    assert facts["level"] == str(level_of(reason.evidence))
    assert facts["reasons"] == (f"junk_{rule.category}:{rule.id}", "large")


def test_the_reasons_keep_their_order() -> None:
    # [0013.17] Strongest first, as the finding has them.
    temp = Reason(Evidence.JUNK_TEMP, "temp-files")
    copy = Reason(Evidence.DUPLICATE_COPY, "/home/alice/kept.tmp")
    facts = subject_of(finding("a.tmp", temp, copy, LARGE, OLD)).facts
    assert facts["reasons"] == ("junk_temp:temp-files", "duplicate_copy", "large", "old")


def test_a_duplicate_names_no_other_copy() -> None:
    # [0013.17] Not the copy that stays, not the group's digest: only that it is a copy.
    kept = entry("report (original).pdf", FOLDER / "Archive")
    copy = entry("report.pdf")
    reason = Reason(Evidence.DUPLICATE_COPY, str(kept.path))
    duplicate = Finding(copy, Level.LIKELY_SAFE, (reason,), Candidate(copy, kept, DIGEST), None)
    assert subject_of(duplicate).facts == {
        "kind": "finding",
        "level": "likely_safe",
        "reasons": ("duplicate_copy",),
        "extension": ".pdf",
    }
    keeper = Finding(kept, Level.REVIEW, (LARGE,), Candidate(kept), DIGEST)
    assert subject_of(keeper).facts == {
        "kind": "finding",
        "level": "review",
        "reasons": ("large",),
        "extension": ".pdf",
    }


@pytest.mark.parametrize(
    ("name", "extension"),
    [
        ("report.PDF", ".pdf"),
        ("archive.tar.gz", ".gz"),
        ("Makefile", ""),
        (".bashrc", ""),
        (".config.json", ".json"),
        ("notes.", ""),  # the same on every Python: pathlib says "." from 3.14
        ("a.b.", ""),
        ("x." + "a" * 15, "." + "a" * 15),  # 16 characters, the dot included
        ("x." + "a" * 16, ""),  # 17
        ("ÉTÉ.ÄÖÜ", ".äöü"),
        ("photo.jpg\u200b", ".jpg"),  # the name is cleaned before its suffix is taken
        ("x." + "a" * 15 + "\u200b", "." + "a" * 15),  # and measured once cleaned
        ("report\x1b]8;;evil.example\x07", ""),  # the dot of an escape sequence is none
    ],
)
def test_the_extension(name: str, extension: str) -> None:
    # [0013.17] The lower-cased suffix of the name, empty when none or over 16 characters.
    assert subject_of(finding(name)).facts["extension"] == extension
    assert subject_of(stay(name)).facts["extension"] == extension


# --- an autostart item [0013.17] ----------------------------------------------------------------


def test_an_autostart_item() -> None:
    # [0013.17] Not the location, the digest, the notes, the shadowed file or the arguments.
    shadowing = item(shadows="/etc/xdg/autostart/my-app.desktop", notes=("OnlyShowIn=GNOME;",))
    facts = subject_of(shadowing).facts
    assert facts == {
        "kind": "autostart",
        "source": "xdg_autostart",
        "scope": "user",
        "name": "My App",
        "program": "app",
        "enabled": True,
    }
    assert list(facts) == ["kind", "source", "scope", "name", "program", "enabled"]
    service = item(source=Source.SERVICE, scope=Scope.SYSTEM, enabled=False)
    expected = {"source": "service", "scope": "system", "enabled": False}
    assert subject_of(service).facts.items() >= expected.items()


@pytest.mark.parametrize(
    ("command", "program"),
    [
        ('"/opt/My App/bin/app" --token=SECRET', "app"),
        ('"C:\\Program Files\\X\\x.exe" /background', "x.exe"),
        ("C:\\Tools\\x.exe /background", "x.exe"),
        ("'/Applications/My App.app/Contents/MacOS/My App' --hidden", "My App"),
        ("/usr/bin/env FOO=1 /opt/app/run", "env"),
        ("  /usr/bin/app\t--tray", "app"),
        ("app", "app"),
        ('"/opt/unterminated/app --x', "app --x"),
        # Unquoted, the first word is all there is: no guess at where a path with spaces ends.
        ("C:\\Program Files\\X\\x.exe /background", "Program"),
        ("/usr/bin/\x1b]0;x/y\x07app --tray", "app"),  # cleaned before the word is taken
        ("/usr/lib/app/", ""),
        ("/opt/" + "p" * 150, "p" * 99 + "…"),
    ],
)
def test_the_program(command: str, program: str) -> None:
    # [0013.17] The last component, after / or \, of the first word or of the quoted part
    # the command starts with.
    assert subject_of(item(command=command)).facts["program"] == program


# --- a file organize leaves where it is [0013.17] -----------------------------------------------


@pytest.mark.parametrize("reason", list(StayReason))
def test_a_stay(reason: StayReason) -> None:
    # [0013.17] The reason and the extension, not the detail: a companion's names another file.
    assert subject_of(stay("Movie.srt", reason)).facts == {
        "kind": "stay",
        "reason": str(reason),
        "extension": ".srt",
    }


# --- only the facts leave, cleaned and cut [0013.17] --------------------------------------------

MARKERS = ["XYZZY", "987654321", "1234567890123456789", "abcdef0123", entry_digest(b"XYZZY")]


def marked() -> list[Result]:
    """One result of each kind, every part that must not leave carrying a marker."""
    folder = Path("/home/XYZZY-user/XYZZY-folder")
    file = FileEntry(folder / "XYZZY-stem.pdf", 987_654_321, 1_234_567_890_123_456_789)
    kept = FileEntry(folder / "XYZZY-kept.pdf", 987_654_321, 1_234_567_890_123_456_789)
    reasons = (
        Reason(Evidence.DUPLICATE_COPY, str(kept.path)),
        Reason(Evidence.LARGE, "941.9 MiB XYZZY"),
        Reason(Evidence.OLD, "unmodified for 987654321 days"),
    )
    digest = "abcdef0123" * 6 + "abcd"
    return [
        Finding(file, Level.LIKELY_SAFE, reasons, Candidate(file, kept, digest), None),
        AutostartItem(
            source=Source.SYSTEMD_USER,
            scope=Scope.USER,
            name="app",
            command="/opt/XYZZY-dir/app --XYZZY-arg=987654321",
            location="/home/XYZZY-user/.config/systemd/user/app.service",
            enabled=True,
            digest=entry_digest(b"XYZZY"),
            notes=("ConditionPathExists=/home/XYZZY-user",),
        ),
        Stay(folder / "XYZZY-stem.srt", StayReason.COMPANION, "XYZZY-stem.mkv"),
    ]


@pytest.mark.parametrize("result", marked(), ids=["finding", "autostart", "stay"])
def test_nothing_but_the_facts_leaves(result: Result) -> None:
    # [0013.17] Path parts, folder, size, times, digest, location, arguments, notes, details:
    # no marker in any byte the server receives.
    subject = subject_of(result)
    with ScriptedOllama(as_json({"response": "An explanation.", "done": True})) as ollama:
        assert generate(ollama.address, "llama3.2", subject.facts) == "An explanation."
    (received,) = ollama.received
    head = "\r\n".join(f"{key}: {value}" for key, value in received.headers)
    sent = f"{received.method} {received.path}\r\n{head}\r\n\r\n".encode() + received.body
    assert [marker for marker in MARKERS if marker.encode() in sent] == []
    prompt = json.loads(json.loads(received.body)["prompt"])
    assert prompt == json.loads(json.dumps(subject.facts))


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("\x1b]0;title\x07My\x1b[31m App\x1b[0m", "My App"),
        ("My\u202eppA", "MyppA"),
        ("My\tApp", "My App"),
        ("  My App  ", "My App"),
        ("first\nsecond\r\n\n  third", "first second third"),  # one line: no fake line
        ("\x1b[2J\u200b\n", ""),
        ("a" * 100, "a" * 100),
        ("a" * 101, "a" * 99 + "…"),
        ("é" * 200, "é" * 99 + "…"),
    ],
)
def test_strings_are_cleaned_and_cut(name: str, shown: str) -> None:
    # [0013.17] Cleaned as an answer is (item 20), on one line, then cut to 100 characters
    # ending with "…".
    assert subject_of(item(name=name)).facts["name"] == shown


def test_a_reason_is_cleaned_and_cut_whole() -> None:
    # [0013.17] The evidence and the rule id are one string.
    escaped = Reason(Evidence.JUNK_CACHE, "python\x1b[2J-bytecode\u202e")
    long = Reason(Evidence.JUNK_TEMP, "rule-" + "x" * 200)
    facts = subject_of(finding("a.tmp", escaped, long)).facts
    assert facts["reasons"] == ("junk_cache:python-bytecode", "junk_temp:rule-" + "x" * 84 + "…")


# --- each subject once, in order [0013.18] ------------------------------------------------------


def test_equal_facts_are_one_subject() -> None:
    # [0013.18] A thousand __pycache__ files are one question, in the order of first appearance.
    pycache = [finding(f"m{n}.cpython-313.pyc", PYCACHE) for n in range(1000)]
    results: list[Result] = [
        finding("report.PDF"),
        *pycache[:500],
        item(),
        finding("Other.pdf"),  # large and old, a .pdf: the same facts as report.PDF
        *pycache[500:],
        item(name="My App\u200b", command="/usr/bin/app"),  # the same once cleaned
        stay(),
        item(enabled=False),
        stay("Other.srt", StayReason.CONFLICT),
        finding("Last.pdf"),  # seen again last: still where it first appeared
    ]
    first: list[Result] = [
        finding(),
        pycache[0],
        item(),
        stay(),
        item(enabled=False),
        stay("Other.srt", StayReason.CONFLICT),
    ]
    assert subjects(results) == tuple(subject_of(result) for result in first)
    assert subjects([]) == ()


def test_a_subject_is_its_facts() -> None:
    # [0013.18] Equal facts, equal and hashable subjects; its facts are a copy.
    one, other = subject_of(finding()), subject_of(finding("Other.pdf"))
    assert (one, hash(one)) == (other, hash(other))
    assert one != subject_of(finding("report.PDF", LARGE))
    facts = one.facts
    facts["level"] = "safe"
    assert one.facts["level"] == "review"


def test_the_largest_subject_fits_the_request_limit() -> None:
    # Item 17's longest facts within item 12's request limit, with item 9's longest model name:
    # a '"' is 4 bytes in the body (\" in the prompt, then \\\" around it), as much as any.
    worst = '"' * 200
    every_reason = tuple(Reason(evidence, worst) for evidence in Evidence)
    name = "x." + '"' * 15
    largest: list[Result] = [
        Finding(entry(name), Level.SAFE, every_reason, Candidate(entry(name)), None),
        item(name=worst, command="/" + worst),
        Stay(FOLDER / name, StayReason.CONFLICT, worst),
    ]
    for result in largest:
        assert len(generate_body("m" * 100, subject_of(result).facts)) <= LIMITS.request_bytes
