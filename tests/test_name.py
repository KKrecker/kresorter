"""The project is Kresorter (decision 0015, item 1): its old name is written in one place, the
item that records it."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = "safe" + "clean"  # made at run time: written whole, this file would name it
RECORD = "docs/decisions/0015-packaging.md"
FOLDERS = (".github", "docs", "src", "tests")
FILES = (".gitignore", "CHANGELOG.md", "README.md", "README.ru.md", "pyproject.toml")


def project_files() -> list[Path]:
    """Every file of the repository but Git's own and the bytecode Python leaves."""
    found = [ROOT / name for name in FILES]
    for folder in FOLDERS:
        found += [
            path
            for path in (ROOT / folder).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ]
    return sorted(found)


def naming(paths: list[Path]) -> dict[str, int]:
    """Each file whose path or text has the old name, in any case, with the times its text has
    it; a file is read as bytes, so that an image is read too."""
    found: dict[str, int] = {}
    old = OLD.encode("ascii")
    for path in paths:
        name = path.relative_to(ROOT).as_posix()
        data = path.read_bytes().lower()
        if OLD in name.lower() or old in data:
            found[name] = data.count(old)
    return found


def test_the_old_name_is_only_in_the_item_that_records_it() -> None:
    # [0015.1]
    assert naming(project_files()) == {RECORD: 1}
