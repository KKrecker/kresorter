"""Nothing in kresorter runs text (decision 0018, item 38).

No module in ``src`` uses ``eval``, ``exec`` or ``compile`` of the built-ins, ``pickle``,
``marshal``, ``shelve``, ``yaml.load``, or ``shell=True``: what a file, a setting, a name or
a model's answer holds is read as data, never as code. The guard reads the AST; a method of
the same name (``re.compile``, a dialog's ``exec``) is no built-in and is let be.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

RUNNERS = frozenset({"eval", "exec", "compile"})
MODULES = frozenset({"pickle", "_pickle", "cPickle", "marshal", "shelve", "dill", "yaml"})


def _module(name: str) -> bool:
    return name.split(".")[0] in MODULES


def runners(source: str) -> list[tuple[int, str]]:
    """Each place in ``source`` that could run text: its line and what it names."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names if _module(alias.name)]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if _module(node.module):
                found.append((node.lineno, node.module))
            elif node.module == "builtins":
                found += [(node.lineno, a.name) for a in node.names if a.name in RUNNERS]
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "builtins"
                and func.attr in RUNNERS
            ):
                found.append((node.lineno, f"builtins.{func.attr}"))
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            first = node.args[0] if node.args else None
            if (
                name in ("__import__", "import_module")
                and isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and _module(first.value)
            ):
                found.append((node.lineno, first.value))
            found += [
                (node.lineno, "shell=True")
                for keyword in node.keywords
                if keyword.arg == "shell"
                and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is False)
            ]
        elif isinstance(node, ast.Name) and node.id in RUNNERS and isinstance(node.ctx, ast.Load):
            found.append((node.lineno, node.id))  # called, or kept to be called later
    return sorted(found)


@pytest.mark.parametrize(
    ("snippet", "named"),
    [
        ("eval(text)", ["eval"]),
        ("exec(text)", ["exec"]),
        ("code = compile(text, 'x', 'exec')", ["compile"]),
        ("import builtins\nbuiltins.eval(text)", ["builtins.eval"]),
        ("from builtins import exec", ["exec"]),
        ("run = eval", ["eval"]),
        ("import pickle", ["pickle"]),
        ("from pickle import loads", ["pickle"]),
        ("import marshal", ["marshal"]),
        ("import shelve", ["shelve"]),
        ("import yaml", ["yaml"]),
        ("from yaml import load", ["yaml"]),
        ("loads = __import__('pickle').loads", ["pickle"]),
        ("import importlib\nm = importlib.import_module('marshal')", ["marshal"]),
        ("run(command, shell=True)", ["shell=True"]),
        ("run(command, shell=flag)", ["shell=True"]),
    ],
)
def test_the_guard_names_each_runner_of_text(snippet: str, named: list[str]) -> None:
    # [0018.38]
    assert [name for _, name in runners(snippet)] == named


def test_the_guard_lets_methods_of_the_same_name_be() -> None:
    # [0018.38]
    source = (
        "import re\nimport json\n_X = re.compile(r'x')\naccepted = dialog.exec()\n"
        "value = json.loads(text)\nrun(command, shell=False)\nimport pickletools_notes\n"
        "self.eval = 1\nfrom . import shelve_notes\n"
    )
    assert runners(source) == []


def test_no_module_runs_text() -> None:
    # [0018.38]
    found = [
        f"{path.relative_to(SRC).as_posix()}:{line}: {name}"
        for path in sorted(SRC.rglob("*.py"))
        for line, name in runners(path.read_text(encoding="utf-8"))
    ]
    assert found == []
