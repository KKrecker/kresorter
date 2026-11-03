"""The release job's checks and files (decision 0015, item 23): ``python packaging/release.py``.

``check TAG``: the tag is ``v`` and ``__version__``, and that version is the changelog's latest,
the first heading ``## [X.Y.Z] - YYYY-MM-DD`` (item 18); otherwise exit 1, before anything is
published. ``notes TAG``: that version's section of the changelog, without its heading: the
GitHub release's text. ``sums FOLDER...``: ``SHA256SUMS.txt``, a line ``<sha256>  <name>`` per
file of the folders, sorted by name, as ``sha256sum --check`` reads it. The release job
installs nothing: the version is read from the source, not imported.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
from collections.abc import Sequence
from pathlib import Path

__all__ = ["ROOT", "ReleaseError", "check", "latest", "main", "notes", "sums", "version"]

ROOT = Path(__file__).resolve().parents[1]
HEADING = re.compile(r"^## \[(?P<version>\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", re.MULTILINE)


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
            print(f"{options.tag}: __version__ and the changelog's latest version are {done}")
        else:
            sys.stdout.write(notes(options.tag, changelog))
    except ReleaseError as error:
        print(f"{step}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
