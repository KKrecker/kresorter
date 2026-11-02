"""The imports of ``src``'s modules, read from their AST as Python resolves them.

``from safeclean import text`` is ``safeclean.text``, a relative import is taken from the
module's package, and a literal name given to ``__import__`` or ``importlib.import_module``
counts too. Shared by the guards of decisions 0013 and 0014.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


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
    return name == "safeclean" or name.startswith("safeclean.")


def sources() -> list[tuple[str, Path]]:
    return [(module_name(path), path) for path in sorted((SRC / "safeclean").rglob("*.py"))]
