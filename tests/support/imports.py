"""The imports of ``src``'s modules, read from their AST as Python resolves them.

``from kresorter import text`` is ``kresorter.text``, a relative import is taken from the
module's package, and a literal name given to ``__import__`` or ``importlib.import_module``
counts too. ``file_uses`` finds the ways a module opens, reads or writes a file. Shared by the
guards of decisions 0013 and 0014.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
FILE_MODULES = frozenset({"tempfile", "sqlite3", "shelve", "pickle"})
FILE_PREFIXES = ("read_", "write_")  # Path.read_text, Path.write_bytes, ...


def module_name(path: Path) -> str:
    parts = path.relative_to(SRC).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def is_module(name: str) -> bool:
    """Whether ``name`` is a module or package of ``src``."""
    where = SRC.joinpath(*name.split("."))
    return where.with_suffix(".py").is_file() or (where / "__init__.py").is_file()


def _package(module: str, is_package: bool) -> list[str]:
    parts = module.split(".")
    return parts if is_package else parts[:-1]


def _dynamic(node: ast.Call) -> str | None:
    """The literal module name of ``__import__("x")`` or ``import_module("x")``, if any."""
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if name in ("__import__", "import_module") and node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    return None


def imports(source: str, module: str, *, is_package: bool = False) -> list[tuple[int, str]]:
    """Each module ``source`` imports, resolved, with its line. ``module`` is its own name."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                package = _package(module, is_package)
                kept = package[: len(package) - node.level + 1]
                base = ".".join([*kept, *([base] if base else [])])
            for alias in node.names:
                inner = f"{base}.{alias.name}"
                found.append((node.lineno, inner if is_module(inner) else base))
        elif isinstance(node, ast.Call) and (name := _dynamic(node)) is not None:
            found.append((node.lineno, name))
    return found


def ours(name: str) -> bool:
    return name == "kresorter" or name.startswith("kresorter.")


def sources() -> list[tuple[str, Path]]:
    return [(module_name(path), path) for path in sorted((SRC / "kresorter").rglob("*.py"))]


def _opens(node: ast.Name | ast.Attribute) -> bool:
    """``open``, or ``.open`` / ``.read_*`` / ``.write_*`` on anything."""
    if isinstance(node, ast.Name):
        return node.id == "open"
    return node.attr == "open" or node.attr.startswith(FILE_PREFIXES)


def file_uses(source: str) -> list[int]:
    """Lines where ``source`` names a way to open, read or write a file."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name | ast.Attribute) and _opens(node):
            lines.append(node.lineno)
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
            lines += [node.lineno for name in names if name.split(".")[0] in FILE_MODULES]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in FILE_MODULES:
                lines.append(node.lineno)
            lines += [node.lineno for alias in node.names if alias.name == "open"]
    return lines
