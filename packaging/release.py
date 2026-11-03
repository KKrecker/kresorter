"""The release job's checks and files (decision 0015, items 23 and 28):
``python packaging/release.py``.

``check TAG``: the tag is ``v`` and ``__version__``, that version is the changelog's latest, the
first heading ``## [X.Y.Z] - YYYY-MM-DD`` (item 18), and ``docs/releases/X.Y.Z.md`` records the
owner's runs on clean machines (item 28, the form in ``docs/releases/README.md``): a run
``## Windows 10 ...``, one ``## Windows 11 ...`` and one ``## Ubuntu NN.NN LTS``, each with a
line ``- **Label**: text`` for every label of ``LABELS``, the Windows ones naming the installer
and the portable zip of the version, the Ubuntu one pipx; otherwise exit 1, with every gap,
before anything is published. ``notes TAG``: that version's section of the changelog, without
its heading: the GitHub release's text. ``sums FOLDER...``: ``SHA256SUMS.txt``, a line
``<sha256>  <name>`` per file of the folders, sorted by name, as ``sha256sum --check`` reads
it. The release job installs nothing: the version is read from the source, not imported.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
from collections.abc import Sequence
from pathlib import Path

__all__ = [
    "LABELS",
    "RECORDS",
    "ROOT",
    "SYSTEMS",
    "WINDOWS",
    "ReleaseError",
    "check",
    "latest",
    "main",
    "notes",
    "record",
    "runs",
    "sums",
    "version",
]

ROOT = Path(__file__).resolve().parents[1]
HEADING = re.compile(r"^## \[(?P<version>\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", re.MULTILINE)
RECORDS = Path("docs", "releases")
# Each system a record has a run on: its name, how a run's heading starts, and what the run's
# Installed names, ``{version}`` the version's.
WINDOWS = ("Kresorter-{version}-setup.exe", "Kresorter-{version}-portable.zip")
SYSTEMS = (
    ("Windows 10", re.compile(r"Windows 10\b"), WINDOWS),
    ("Windows 11", re.compile(r"Windows 11\b"), WINDOWS),
    ("an Ubuntu LTS", re.compile(r"Ubuntu \d+\.\d+(?:\.\d+)? LTS\b"), ("pipx",)),
)
# What each run says: the system and its version, how it was installed, what was done and seen.
LABELS = (
    "System",
    "Installed",
    "The window on a screen",
    "A scan",
    "A file quarantined and restored",
    "Each page",
    "A folder sorted and its batch undone",
    "The uninstall",
)
LINE = re.compile(r"- \*\*(?P<label>.+?)\*\*:(?P<text>.*)")


class ReleaseError(Exception):
    """Why the release stops; its message says it."""


def version(source: str) -> str:
    """The ``__version__`` that ``source``, the package's ``__init__.py``, assigns."""
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.Assign)
            and [ast.unparse(target) for target in node.targets] == ["__version__"]
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise ReleaseError("the package's __init__.py has no __version__")


def latest(changelog: str) -> str:
    found = HEADING.search(changelog)
    if found is None:
        raise ReleaseError("the changelog has no version yet")
    return found["version"]


def check(tag: str, source: str, changelog: str) -> str:
    """``__version__``, when ``tag`` is ``v`` and it, and it is the changelog's latest."""
    expected = version(source)
    if tag != f"v{expected}":
        raise ReleaseError(f"the tag {tag!r} is not {f'v{expected}'!r} (__version__)")
    last = latest(changelog)
    if last != expected:
        raise ReleaseError(
            f"the changelog's latest version is {last}, not {expected} (__version__)"
        )
    return expected


def notes(tag: str, changelog: str) -> str:
    """The section of the tag's version, up to the next heading of its level."""
    wanted = tag.removeprefix("v")
    headings = list(HEADING.finditer(changelog))
    for index, heading in enumerate(headings):
        if heading["version"] == wanted:
            end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
            return changelog[heading.end() : end].strip("\n") + "\n"
    raise ReleaseError(f"the changelog has no section {wanted}")


def runs(text: str) -> dict[str, dict[str, str]]:
    """The runs of a record, by their heading ``## ...``: each line ``- **Label**: text``, by
    its label, its text joined with the indented lines under it."""
    found: dict[str, dict[str, str]] = {}
    said: dict[str, str] = {}
    label = ""
    for line in text.splitlines():
        if line.startswith("## "):
            said, label = found.setdefault(line[3:].strip(), {}), ""
        elif (field := LINE.fullmatch(line)) is not None:
            label = field["label"]
            said[label] = field["text"].strip()
        elif line.startswith("  ") and label:
            said[label] = f"{said[label]} {line.strip()}".strip()
        else:
            label = ""
    return found


def record(version: str, text: str) -> list[str]:
    """The headings of the runs ``text``, the record of ``version``, has, each system's in the
    order of ``SYSTEMS``, when it is complete; otherwise every gap, at once."""
    found = runs(text)
    gaps: list[str] = []
    done: list[str] = []
    for system, heading, names in SYSTEMS:
        theirs = [name for name in found if heading.match(name)]
        if not theirs:
            gaps.append(f"no run on {system}")
        for name in theirs:
            said = found[name]
            gaps += [f"{name}: nothing under {label!r}" for label in LABELS if not said.get(label)]
            installed = said.get("Installed", "")
            needed = [each.format(version=version) for each in names]
            gaps += [
                f"{name}: 'Installed' names no {each}"
                for each in needed
                if installed and each not in installed
            ]
        done += theirs
    if gaps:
        raise ReleaseError(f"the record of {version} is not complete: {'; '.join(gaps)}")
    return done


def sums(folders: Sequence[Path]) -> str:
    files: dict[str, Path] = {}
    for folder in folders:
        for path in sorted(folder.iterdir()):
            if path.name in files:
                raise ReleaseError(f"two files are named {path.name}")
            files[path.name] = path
    return "".join(
        f"{hashlib.sha256(files[name].read_bytes()).hexdigest()}  {name}\n"
        for name in sorted(files)
    )


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(prog="release.py", description="The release job's steps.")
    steps = parser.add_subparsers(dest="step", required=True)
    for name, text in (("check", "check the tag"), ("notes", "the release's text")):
        steps.add_parser(name, help=text).add_argument("tag", help="the tag, vX.Y.Z")
    steps.add_parser("sums", help="SHA256SUMS.txt").add_argument(
        "folders", nargs="+", type=Path, help="the folders of what is published"
    )
    options = parser.parse_args(argv)
    step: str = options.step
    try:
        if step == "sums":
            sys.stdout.write(sums(options.folders))
            return 0
        source = (root / "src" / "kresorter" / "__init__.py").read_text(encoding="utf-8")
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        if step == "check":
            done = check(options.tag, source, changelog)
            path = RECORDS / f"{done}.md"
            if not (root / path).is_file():
                raise ReleaseError(
                    f"no {path.as_posix()}, the record of the runs on clean machines"
                )
            seen = record(done, (root / path).read_text(encoding="utf-8"))
            print(f"{options.tag}: __version__ and the changelog's latest version are {done}")
            print(f"{path.as_posix()}: the runs on {', '.join(seen)}")
        else:
            sys.stdout.write(notes(options.tag, changelog))
    except ReleaseError as error:
        print(f"{step}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
